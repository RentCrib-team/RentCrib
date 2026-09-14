import hashlib
import json
import os
import re
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
from django.utils import timezone


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PROVENANCE_PREFIX = "city_image_provenance"

SEARCH_NAME_OVERRIDES = {
    "bangor-northern-ireland": "Bangor Northern Ireland",
    "bangor-wales": "Bangor Wales",
    "kingston-upon-hull": "Hull",
    "londonderry": "Derry Londonderry",
    "newcastle-upon-tyne": "Newcastle upon Tyne",
    "st-asaph": "Saint Asaph",
    "st-davids": "Saint Davids",
}

CITY_MATCH_ALIASES = {
    "bangor-northern-ireland": ("Bangor Northern Ireland",),
    "bangor-wales": ("Bangor Wales",),
    "kingston-upon-hull": ("Kingston upon Hull", "Hull"),
    "londonderry": ("Londonderry", "Derry"),
    "newcastle-upon-tyne": ("Newcastle upon Tyne", "Newcastle"),
    "st-asaph": ("St Asaph", "Saint Asaph"),
    "st-davids": ("St Davids", "Saint Davids"),
}

NIGHT_TERMS = ("night", "nighttime", "evening", "city lights", "after dark")


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


def _city_time_preference(city):
    """Alternate cities between night-leaning and day-leaning imagery."""
    return "night" if int(city.pk) % 2 else "day"


def _search_queries(item):
    slug = _clean(item.get("slug")).lower()
    display_name = _clean(item.get("display_name") or item.get("name"))
    nation = _clean(item.get("nation"))
    search_name = SEARCH_NAME_OVERRIDES.get(slug, display_name)
    return [
        f"{search_name} {nation} United Kingdom city skyline".strip(),
        f"{search_name} {nation} United Kingdom city centre".strip(),
        f"{search_name} {nation} United Kingdom landmark".strip(),
        f"{search_name} {nation} United Kingdom city skyline at night".strip(),
        f"{search_name} {nation} United Kingdom city lights at night".strip(),
    ]


def _download_url(photo):
    src = photo.get("src") or {}
    return (
        src.get("large2x")
        or src.get("large")
        or src.get("landscape")
        or src.get("medium")
    )


def _match_text(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).split())


def _city_match_terms(item):
    slug = _clean(item.get("slug")).lower()
    aliases = CITY_MATCH_ALIASES.get(slug)
    if aliases:
        return tuple(_match_text(value) for value in aliases if _match_text(value))
    display_name = _clean(item.get("display_name") or item.get("name"))
    term = _match_text(display_name)
    return (term,) if term else ()


def _photo_matches_city(photo, *, item):
    """Require the Pexels photo metadata itself to identify the target city."""
    metadata = _match_text(" ".join((_clean(photo.get("alt")), _clean(photo.get("url")))))
    if not metadata:
        return False
    padded = f" {metadata} "
    return any(f" {term} " in padded for term in _city_match_terms(item))


def _photo_relevance_score(photo, *, item, query, preferred_time=None):
    slug = _clean(item.get("slug")).lower()
    display_name = _clean(item.get("display_name") or item.get("name"))
    nation = _clean(item.get("nation"))
    search_name = SEARCH_NAME_OVERRIDES.get(slug, display_name)

    haystack = " ".join(
        _clean(value).lower()
        for value in (
            photo.get("alt"),
            photo.get("url"),
            photo.get("photographer"),
            query,
        )
        if _clean(value)
    )

    score = 0
    for token, weight in (
        (display_name.lower(), 8),
        (search_name.lower(), 8),
        (nation.lower(), 2),
        ("city", 2),
        ("skyline", 4),
        ("city centre", 4),
        ("city center", 4),
        ("landmark", 3),
        ("architecture", 2),
        ("building", 1),
        ("street", 1),
    ):
        if token and token in haystack:
            score += weight

    for token, penalty in (
        ("portrait", 6),
        ("person", 6),
        ("people", 5),
        ("food", 5),
        ("animal", 5),
        ("beach", 3),
        ("mountain", 3),
        ("forest", 3),
        ("flower", 3),
        ("car interior", 4),
    ):
        if token in haystack:
            score -= penalty

    is_night = any(term in haystack for term in NIGHT_TERMS)
    if preferred_time == "night" and is_night:
        score += 7
    elif preferred_time == "day" and not is_night:
        score += 5

    width = photo.get("width") or 0
    height = photo.get("height") or 0
    if width and height and width >= height:
        score += 2
    if width and height and width >= 1200 and height >= 675:
        score += 2

    return score


def _find_photo_candidates(
    *,
    item,
    api_key,
    http_get,
    excluded_photo_ids=None,
    preferred_time=None,
):
    last_error = None
    excluded_photo_ids = {str(value) for value in (excluded_photo_ids or ()) if value}
    candidates = {}

    for query in _search_queries(item):
        try:
            response = http_get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "orientation": "landscape",
                    "size": "large",
                    "per_page": 15,
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

        for index, photo in enumerate(photos):
            photo_id = str(photo.get("id") or "")
            if not photo_id or photo_id in excluded_photo_ids or not _download_url(photo):
                continue
            if not _photo_matches_city(photo, item=item):
                continue
            score = _photo_relevance_score(
                photo,
                item=item,
                query=query,
                preferred_time=preferred_time,
            )
            candidate = (score, -index, photo, query)
            current = candidates.get(photo_id)
            if current is None or candidate[:2] > current[:2]:
                candidates[photo_id] = candidate

    if candidates:
        return sorted(candidates.values(), key=lambda candidate: candidate[:2], reverse=True)
    if last_error:
        raise RuntimeError(f"Pexels search failed: {last_error}") from last_error
    raise RuntimeError("Pexels returned no unused usable city-matched image")


def _normalise_downloaded_image(*, content, slug):
    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            if width < 640 or height < 360:
                raise ValueError(
                    f"source image is too small ({width}x{height}); minimum is 640x360"
                )
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


def _file_sha256(file_obj):
    file_obj.seek(0)
    digest = hashlib.sha256()
    while True:
        chunk = file_obj.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    file_obj.seek(0)
    return digest.hexdigest()


def _stored_file_sha256(storage, name):
    with storage.open(name, "rb") as handle:
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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


def _used_assignments(storage, catalogue, *, exclude_slug):
    used_photo_ids = set()
    used_hashes = set()

    for item in catalogue:
        other_slug = _clean(item.get("slug")).lower()
        if not other_slug or other_slug == exclude_slug:
            continue
        provenance_name = f"{PROVENANCE_PREFIX}/{other_slug}.json"
        if not storage.exists(provenance_name):
            continue
        try:
            with storage.open(provenance_name, "rb") as handle:
                provenance = json.loads(handle.read().decode("utf-8"))
        except Exception:
            continue

        photo_id = _clean(provenance.get("provider_photo_id"))
        if photo_id:
            used_photo_ids.add(photo_id)

        content_sha256 = _clean(provenance.get("content_sha256"))
        if not content_sha256:
            stored_image = _clean(provenance.get("stored_image"))
            if stored_image and storage.exists(stored_image):
                try:
                    content_sha256 = _stored_file_sha256(storage, stored_image)
                except Exception:
                    content_sha256 = ""
                if content_sha256:
                    provenance["content_sha256"] = content_sha256
                    _save_provenance(storage, other_slug, provenance)
        if content_sha256:
            used_hashes.add(content_sha256)

    return used_photo_ids, used_hashes


def _delete_safely(storage, name):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:
        pass


def autofill_city_image(
    city_id,
    *,
    api_key=None,
    http_get=None,
    city_model=None,
    catalogue=None,
    prepare_image=None,
    atomic_context=None,
    now_func=None,
):
    """Populate one missing canonical city image from Pexels without reusing an image."""

    resolved_key = _api_key(api_key)
    if not resolved_key:
        return {
            "status": "disabled",
            "city_id": city_id,
            "slug": "",
            "error": "PEXELS_API_KEY is not configured",
        }

    if city_model is None or catalogue is None or prepare_image is None:
        runtime_city_model, runtime_catalogue, runtime_prepare_image = _runtime_dependencies()
        city_model = city_model or runtime_city_model
        catalogue = catalogue or runtime_catalogue
        prepare_image = prepare_image or runtime_prepare_image

    http_get = http_get or requests.get
    atomic_context = atomic_context or transaction.atomic
    now_func = now_func or timezone.now
    catalogue_index = _catalogue_by_slug(catalogue)

    image_storage = None
    new_image_name = ""
    provenance_name = ""
    slug = ""

    try:
        context = atomic_context() if callable(atomic_context) else nullcontext()
        with context:
            lock_qs = city_model.objects.select_for_update().filter(is_active=True)
            list(lock_qs.order_by("pk").values_list("pk", flat=True))

            city = city_model.objects.select_for_update().get(pk=city_id)
            slug = _clean(city.slug).lower()
            if city.image:
                return {"status": "existing", "city_id": city_id, "slug": slug}
            if not getattr(city, "is_active", True):
                return {"status": "inactive", "city_id": city_id, "slug": slug}

            item = catalogue_index.get(slug)
            if item is None:
                raise RuntimeError("City is missing from the official UK catalogue")

            preferred_time = _city_time_preference(city)
            image_storage = city.image.storage
            used_photo_ids, used_hashes = _used_assignments(
                image_storage,
                catalogue,
                exclude_slug=slug,
            )
            candidates = _find_photo_candidates(
                item=item,
                api_key=resolved_key,
                http_get=http_get,
                excluded_photo_ids=used_photo_ids,
                preferred_time=preferred_time,
            )

            last_candidate_error = None
            selected = None
            prepared = None
            content_sha256 = ""

            for relevance_score, _, photo, query in candidates:
                try:
                    download_url = _download_url(photo)
                    response = http_get(download_url, timeout=60)
                    response.raise_for_status()
                    uploaded = _normalise_downloaded_image(
                        content=response.content,
                        slug=slug,
                    )
                    candidate_prepared = prepare_image(uploaded)
                    candidate_hash = _file_sha256(candidate_prepared)
                    if candidate_hash in used_hashes:
                        continue
                    selected = (photo, query, relevance_score)
                    prepared = candidate_prepared
                    content_sha256 = candidate_hash
                    break
                except Exception as exc:
                    last_candidate_error = exc
                    continue

            if selected is None or prepared is None:
                if last_candidate_error:
                    raise RuntimeError(
                        f"Pexels returned no unique usable city image: {last_candidate_error}"
                    ) from last_candidate_error
                raise RuntimeError("Pexels returned no unique usable city image")

            photo, query, relevance_score = selected
            target_name = _prepared_filename(slug, prepared)
            city.image.save(target_name, prepared, save=False)
            new_image_name = _clean(city.image.name)

            photographer = _clean(photo.get("photographer")) or "Unknown photographer"
            provenance = {
                "city_slug": slug,
                "city_name": _clean(item.get("display_name") or item.get("name") or city.name),
                "provider": "Pexels",
                "provider_photo_id": str(photo.get("id") or ""),
                "content_sha256": content_sha256,
                "photographer": photographer,
                "source_url": _clean(photo.get("url")) or "https://www.pexels.com/",
                "license_name": "Pexels License",
                "license_url": PEXELS_LICENSE_URL,
                "credit": f"Photo by {photographer} on Pexels",
                "rights_confirmed": True,
                "search_query": query,
                "relevance_score": relevance_score,
                "time_preference": preferred_time,
                "stored_image": new_image_name,
                "recorded_at": now_func().isoformat(),
            }
            provenance_name = _save_provenance(image_storage, slug, provenance)

            display_name = _clean(item.get("display_name") or item.get("name"))
            city.image_alt = city.image_alt or f"{display_name} city view"
            city.save(update_fields=["image", "image_alt", "updated_at"])

        return {
            "status": "imported",
            "city_id": city_id,
            "slug": slug,
            "image": new_image_name,
            "provenance": provenance_name,
        }

    except Exception as exc:
        _delete_safely(image_storage, new_image_name)
        _delete_safely(image_storage, provenance_name)
        return {
            "status": "failed",
            "city_id": city_id,
            "slug": slug,
            "error": str(exc),
        }
