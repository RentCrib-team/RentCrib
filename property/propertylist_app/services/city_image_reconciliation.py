import json
from contextlib import nullcontext

import requests
from django.apps import apps
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from propertylist_app.services.city_image_autofill import (
    NIGHT_TERMS,
    PEXELS_LICENSE_URL,
    PROVENANCE_PREFIX,
    _api_key,
    _catalogue_by_slug,
    _clean,
    _delete_safely,
    _download_url,
    _file_sha256,
    _find_photo_candidates,
    _normalise_downloaded_image,
    _prepared_filename,
    _stored_file_sha256,
    _used_assignments,
)


def _runtime_dependencies():
    from propertylist_app.data.uk_cities import OFFICIAL_UK_CITIES
    from propertylist_app.services.city_images import prepare_city_image

    city_model = apps.get_model("propertylist_app", "City")
    return city_model, OFFICIAL_UK_CITIES, prepare_city_image


def _query_is_night(query):
    value = _clean(query).lower()
    return any(term in value for term in NIGHT_TERMS)


def _read_provenance(storage, slug):
    name = f"{PROVENANCE_PREFIX}/{slug}.json"
    if not storage.exists(name):
        return {}
    try:
        with storage.open(name, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    except Exception:
        return {}


def _city_image_records(cities):
    records = []
    for index, city in enumerate(cities):
        image_name = _clean(getattr(city.image, "name", ""))
        if not image_name:
            continue
        storage = city.image.storage
        provenance = _read_provenance(storage, _clean(city.slug).lower())
        content_sha256 = ""
        if storage.exists(image_name):
            try:
                content_sha256 = _stored_file_sha256(storage, image_name)
            except Exception:
                content_sha256 = ""
        records.append(
            {
                "index": index,
                "city": city,
                "photo_id": _clean(provenance.get("provider_photo_id")),
                "content_sha256": content_sha256,
                "is_night": _query_is_night(provenance.get("search_query")),
            }
        )
    return records


def _duplicate_city_ids(records):
    parent = list(range(len(records)))

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    seen = {}
    for index, record in enumerate(records):
        for key in (
            ("photo_id", record["photo_id"]) if record["photo_id"] else None,
            ("content_sha256", record["content_sha256"])
            if record["content_sha256"]
            else None,
        ):
            if key is None:
                continue
            if key in seen:
                union(seen[key], index)
            else:
                seen[key] = index

    components = {}
    for index, record in enumerate(records):
        components.setdefault(find(index), []).append(record)

    duplicate_ids = []
    for members in components.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda item: item["index"])
        duplicate_ids.extend(item["city"].pk for item in ordered[1:])
    return duplicate_ids


def _restore_provenance(storage, name, content):
    if storage.exists(name):
        storage.delete(name)
    if content is not None:
        storage.save(name, ContentFile(content))


def _replace_existing_city_image(
    city_id,
    *,
    preferred_time,
    api_key=None,
    http_get=None,
    city_model=None,
    catalogue=None,
    prepare_image=None,
    atomic_context=None,
    now_func=None,
    used_photo_ids=None,
    used_hashes=None,
):
    """Replace one existing city image without clearing its approved DB image first."""

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
    old_provenance = None
    slug = ""

    try:
        context = atomic_context() if callable(atomic_context) else nullcontext()
        with context:
            lock_qs = city_model.objects.select_for_update().filter(is_active=True)
            list(lock_qs.order_by("pk").values_list("pk", flat=True))

            city = city_model.objects.select_for_update().get(pk=city_id)
            slug = _clean(city.slug).lower()
            if not getattr(city, "is_active", True):
                return {"status": "inactive", "city_id": city_id, "slug": slug}
            if not city.image:
                return {
                    "status": "missing",
                    "city_id": city_id,
                    "slug": slug,
                    "error": "City has no existing image to reconcile",
                }

            item = catalogue_index.get(slug)
            if item is None:
                raise RuntimeError("City is missing from the official UK catalogue")

            image_storage = city.image.storage
            provenance_name = f"{PROVENANCE_PREFIX}/{slug}.json"
            if image_storage.exists(provenance_name):
                with image_storage.open(provenance_name, "rb") as handle:
                    old_provenance = handle.read()

            if used_photo_ids is None or used_hashes is None:
                candidate_photo_ids, candidate_hashes = _used_assignments(
                    image_storage,
                    catalogue,
                    exclude_slug=slug,
                )
            else:
                candidate_photo_ids = set(used_photo_ids)
                candidate_hashes = set(used_hashes)

            candidates = _find_photo_candidates(
                item=item,
                api_key=resolved_key,
                http_get=http_get,
                excluded_photo_ids=candidate_photo_ids,
                preferred_time=preferred_time,
            )

            last_candidate_error = None
            selected = None
            prepared = None
            content_sha256 = ""

            for relevance_score, _, photo, query in candidates:
                try:
                    response = http_get(_download_url(photo), timeout=60)
                    response.raise_for_status()
                    uploaded = _normalise_downloaded_image(
                        content=response.content,
                        slug=slug,
                    )
                    candidate_prepared = prepare_image(uploaded)
                    candidate_hash = _file_sha256(candidate_prepared)
                    if candidate_hash in candidate_hashes:
                        continue
                    selected = (photo, query, relevance_score)
                    prepared = candidate_prepared
                    content_sha256 = candidate_hash
                    break
                except Exception as exc:
                    last_candidate_error = exc

            if selected is None or prepared is None:
                if last_candidate_error:
                    raise RuntimeError(
                        f"Pexels returned no unique usable replacement: {last_candidate_error}"
                    ) from last_candidate_error
                raise RuntimeError("Pexels returned no unique usable replacement")

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

            city.image_alt = city.image_alt or f"{_clean(item.get('display_name') or item.get('name'))} city view"
            city.save(update_fields=["image", "image_alt", "updated_at"])

            _restore_provenance(
                image_storage,
                provenance_name,
                json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ).encode("utf-8"),
            )

        return {
            "status": "imported",
            "city_id": city_id,
            "slug": slug,
            "image": new_image_name,
            "provenance": provenance_name,
            "provider_photo_id": provenance["provider_photo_id"],
            "content_sha256": content_sha256,
            "search_query": query,
            "time_preference": preferred_time,
        }

    except Exception as exc:
        _delete_safely(image_storage, new_image_name)
        if image_storage and provenance_name:
            try:
                _restore_provenance(image_storage, provenance_name, old_provenance)
            except Exception:
                pass
        return {
            "status": "failed",
            "city_id": city_id,
            "slug": slug,
            "error": str(exc),
        }


def reconcile_duplicate_city_images(
    *,
    cities=None,
    city_model=None,
    catalogue=None,
    replace_image=None,
):
    """Relist duplicate approved city images only, preferring the underrepresented time of day."""

    if city_model is None or catalogue is None:
        runtime_city_model, runtime_catalogue, _ = _runtime_dependencies()
        city_model = city_model or runtime_city_model
        catalogue = catalogue or runtime_catalogue

    if cities is None:
        cities = list(
            city_model.objects.filter(is_active=True, image_is_approved=True)
            .exclude(image="")
            .exclude(image__isnull=True)
            .order_by("display_order", "name", "pk")
        )
    else:
        cities = list(cities)

    records = _city_image_records(cities)
    duplicate_ids = _duplicate_city_ids(records)
    duplicate_set = set(duplicate_ids)

    night_count = sum(
        1
        for record in records
        if record["city"].pk not in duplicate_set and record["is_night"]
    )
    day_count = sum(
        1
        for record in records
        if record["city"].pk not in duplicate_set and not record["is_night"]
    )

    used_photo_ids = {
        record["photo_id"] for record in records if record["photo_id"]
    }
    used_hashes = {
        record["content_sha256"]
        for record in records
        if record["content_sha256"]
    }

    replace_image = replace_image or _replace_existing_city_image
    replaced = []
    failed = []

    city_by_id = {city.pk: city for city in cities}
    for city_id in duplicate_ids:
        preferred_time = "night" if night_count <= day_count else "day"
        result = replace_image(
            city_id,
            preferred_time=preferred_time,
            city_model=city_model,
            catalogue=catalogue,
            used_photo_ids=used_photo_ids,
            used_hashes=used_hashes,
        )
        if result.get("status") == "imported":
            replaced.append(
                {
                    "city_id": city_id,
                    "city": getattr(city_by_id.get(city_id), "name", ""),
                    "time_preference": preferred_time,
                }
            )
            provider_photo_id = _clean(result.get("provider_photo_id"))
            content_sha256 = _clean(result.get("content_sha256"))
            if provider_photo_id:
                used_photo_ids.add(provider_photo_id)
            if content_sha256:
                used_hashes.add(content_sha256)
            if _query_is_night(result.get("search_query")):
                night_count += 1
            else:
                day_count += 1
        else:
            failed.append(
                {
                    "city_id": city_id,
                    "city": getattr(city_by_id.get(city_id), "name", ""),
                    "error": result.get("error") or result.get("status"),
                }
            )

    return {
        "status": "ok" if not failed else "partial",
        "duplicate_city_ids": duplicate_ids,
        "replaced": replaced,
        "failed": failed,
        "night_count": night_count,
        "day_count": day_count,
    }
