import json
import os
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps
from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PROVENANCE_PREFIX = "city_image_provenance"
DEFAULT_BATCH_LIMIT = 5

SEARCH_NAME_OVERRIDES = {
    "bangor-northern-ireland": "Bangor Northern Ireland",
    "bangor-wales": "Bangor Wales",
    "kingston-upon-hull": "Hull",
    "londonderry": "Derry Londonderry",
    "newcastle-upon-tyne": "Newcastle upon Tyne",
    "st-asaph": "Saint Asaph",
    "st-davids": "Saint Davids",
}


def _clean(value):
    return str(value or "").strip()


def _runtime_dependencies():
    from propertylist_app.data.uk_cities import OFFICIAL_UK_CITIES
    from propertylist_app.services.city_images import prepare_city_image

    city_model = apps.get_model("propertylist_app", "City")
    return city_model, OFFICIAL_UK_CITIES, prepare_city_image


def _api_key(explicit_key=None):
    if explicit_key is not None:
        return _clean(explicit_key)
    return _clean(
        getattr(settings, "PEXELS_API_KEY", "")
        or os.getenv("PEXELS_API_KEY", "")
    )


def _catalogue_by_slug(catalogue):
    return {
        _clean(item.get("slug")).lower(): item
        for item in catalogue
        if _clean(item.get("slug"))
    }


def _search_queries(item):
    slug = _clean(item.get("slug")).lower()
    display_name = _clean(item.get("display_name") or item.get("name"))
    nation = _clean(item.get("nation"))
    search_name = SEARCH_NAME_OVERRIDES.get(slug, display_name)

    return [
        f"{search_name} {nation} United Kingdom city skyline".strip(),
        f"{search_name} {nation} United Kingdom city centre".strip(),
        f"{search_name} {nation} United Kingdom".strip(),
    ]


def _download_url(photo):
    src = photo.get("src") or {}
    return (
        src.get("large2x")
        or src.get("large")
        or src.get("landscape")
        or src.get("medium")
    )


def _find_photo(*, item, api_key, http_get):
    last_error = None
    for query in _search_queries(item):
        try:
            response = http_get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "orientation": "landscape",
                    "size": "large",
                    "per_page": 5,
                    "page": 1,
                },
                timeout=30,
            )
            if response.status_code == 401:
                raise RuntimeError("Pexels API rejected PEXELS_API_KEY")
            response.raise_for_status()
            photos = (response.json() or {}).get("photos") or []
        except Exception as exc:
            last_error = exc
            continue

        for photo in photos:
            if _download_url(photo):
                return photo, query

    if last_error:
        raise RuntimeError(f"Pexels search failed: {last_error}") from last_error
    raise RuntimeError("Pexels returned no usable city image")


def _normalise_downloaded_image(*, content, slug):
    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(
                image,
                (1600, 900),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            handle = BytesIO()
            image.save(
                handle,
                "JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
    except Exception as exc:
        raise RuntimeError(f"Downloaded city image is invalid: {exc}") from exc

    return SimpleUploadedFile(
        name=f"{slug}.jpg",
        content=handle.getvalue(),
        content_type="image/jpeg",
    )


def _prepared_filename(slug, prepared):
    suffix = Path(_clean(getattr(prepared, "name", ""))).suffix.lower()
    return f"{slug}{suffix or '.jpg'}"


def _provenance_payload(*, city, item, photo, query, image_name, now):
    photographer = _clean(photo.get("photographer")) or "Unknown photographer"
    return {
        "city_slug": city.slug,
        "city_name": _clean(item.get("display_name") or item.get("name") or city.name),
        "provider": "Pexels",
        "provider_photo_id": str(photo.get("id") or ""),
        "photographer": photographer,
        "source_url": _clean(photo.get("url")) or "https://www.pexels.com/",
        "license_name": "Pexels License",
        "license_url": PEXELS_LICENSE_URL,
        "credit": f"Photo by {photographer} on Pexels",
        "rights_confirmed": True,
        "search_query": query,
        "stored_image": image_name,
        "recorded_at": now.isoformat(),
    }


def _save_provenance(storage, slug, payload):
    name = f"{PROVENANCE_PREFIX}/{slug}.json"
    if storage.exists(name):
        storage.delete(name)
    return storage.save(
        name,
        ContentFile(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        ),
    )


def _delete_safely(storage, name):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:
        pass


def autofill_missing_city_images(
    *,
    limit=DEFAULT_BATCH_LIMIT,
    api_key=None,
    http_get=None,
    city_model=None,
    catalogue=None,
    prepare_image=None,
    atomic_context=None,
    now_func=None,
):
    """Populate a bounded batch of missing canonical city images.

    Existing city images are never replaced. Each successful third-party image
    is validated through RentCrib's normal city-image pipeline and receives a
    durable provenance JSON sidecar in the same configured media storage.
    """

    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")

    resolved_key = _api_key(api_key)
    if not resolved_key:
        return {
            "status": "disabled",
            "reason": "PEXELS_API_KEY is not configured",
            "attempted": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

    if city_model is None or catalogue is None or prepare_image is None:
        runtime_city_model, runtime_catalogue, runtime_prepare_image = _runtime_dependencies()
        city_model = city_model or runtime_city_model
        catalogue = catalogue or runtime_catalogue
        prepare_image = prepare_image or runtime_prepare_image

    http_get = http_get or requests.get
    now_func = now_func or timezone.now
    atomic_context = atomic_context or transaction.atomic
    catalogue_index = _catalogue_by_slug(catalogue)

    queryset = (
        city_model.objects.filter(is_active=True)
        .filter(Q(image="") | Q(image__isnull=True))
        .order_by("display_order", "name")
    )
    city_ids = list(queryset.values_list("pk", flat=True)[:limit])

    result = {
        "status": "ok",
        "attempted": len(city_ids),
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for city_id in city_ids:
        image_storage = None
        new_image_name = ""
        provenance_name = ""
        slug = ""

        try:
            context = atomic_context() if callable(atomic_context) else nullcontext()
            with context:
                city = city_model.objects.select_for_update().get(pk=city_id)
                slug = _clean(city.slug).lower()

                if city.image:
                    result["skipped"] += 1
                    continue

                item = catalogue_index.get(slug)
                if item is None:
                    raise RuntimeError("City is missing from the official UK catalogue")

                photo, query = _find_photo(
                    item=item,
                    api_key=resolved_key,
                    http_get=http_get,
                )
                download_url = _download_url(photo)
                image_response = http_get(download_url, timeout=60)
                image_response.raise_for_status()

                uploaded = _normalise_downloaded_image(
                    content=image_response.content,
                    slug=slug,
                )
                prepared = prepare_image(uploaded)
                target_name = _prepared_filename(slug, prepared)

                image_storage = city.image.storage
                city.image.save(target_name, prepared, save=False)
                new_image_name = _clean(city.image.name)

                payload = _provenance_payload(
                    city=city,
                    item=item,
                    photo=photo,
                    query=query,
                    image_name=new_image_name,
                    now=now_func(),
                )
                provenance_name = _save_provenance(
                    image_storage,
                    slug,
                    payload,
                )

                display_name = _clean(item.get("display_name") or item.get("name"))
                city.image_alt = city.image_alt or f"{display_name} city view"
                city.save(update_fields=["image", "image_alt", "updated_at"])

            result["imported"] += 1

        except Exception as exc:
            _delete_safely(image_storage, new_image_name)
            _delete_safely(image_storage, provenance_name)
            result["failed"] += 1
            result["errors"].append(
                {
                    "city_id": city_id,
                    "slug": slug,
                    "error": str(exc),
                }
            )

    return result
