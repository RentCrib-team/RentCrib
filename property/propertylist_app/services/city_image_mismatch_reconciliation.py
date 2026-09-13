import requests

from propertylist_app.services.city_image_autofill import (
    _api_key,
    _catalogue_by_slug,
    _clean,
    _photo_matches_city,
)
from propertylist_app.services.city_image_reconciliation import (
    _bounded_http_get,
    _city_image_records,
    _emit_progress,
    _replace_existing_city_image,
    _runtime_dependencies,
)


PEXELS_PHOTO_URL = "https://api.pexels.com/v1/photos/{photo_id}"


def _fetch_pexels_photo(*, photo_id, api_key, http_get):
    response = _bounded_http_get(
        http_get,
        PEXELS_PHOTO_URL.format(photo_id=photo_id),
        headers={"Authorization": api_key},
    )
    if response.status_code == 401:
        raise RuntimeError("Pexels API rejected PEXELS_API_KEY")
    response.raise_for_status()
    return response.json() or {}


def reconcile_mismatched_city_images(
    *,
    cities=None,
    city_model=None,
    catalogue=None,
    replace_image=None,
    http_get=None,
    api_key=None,
    progress=None,
):
    """Replace approved Pexels images whose photo metadata does not identify their city."""

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

    resolved_key = _api_key(api_key)
    if not resolved_key:
        return {
            "status": "disabled",
            "matched": [],
            "mismatched_city_ids": [],
            "replaced": [],
            "failed": [],
            "unknown": [],
            "error": "PEXELS_API_KEY is not configured",
        }

    raw_http_get = http_get or requests.get
    catalogue_index = _catalogue_by_slug(catalogue)
    records = _city_image_records(cities)
    city_by_id = {city.pk: city for city in cities}

    used_photo_ids = {
        record["photo_id"] for record in records if record["photo_id"]
    }
    used_hashes = {
        record["content_sha256"]
        for record in records
        if record["content_sha256"]
    }

    matched = []
    mismatched_records = []
    unknown = []

    _emit_progress(
        progress,
        f"Auditing {len(records)} approved city images for city mismatch",
    )

    for position, record in enumerate(records, start=1):
        city = record["city"]
        city_name = getattr(city, "name", "")
        slug = _clean(getattr(city, "slug", "")).lower()
        item = catalogue_index.get(slug)
        photo_id = _clean(record.get("photo_id"))

        if item is None:
            error = "City is missing from the official UK catalogue"
            unknown.append({"city_id": city.pk, "city": city_name, "error": error})
            _emit_progress(
                progress,
                f"[{position}/{len(records)}] {city_name}: unknown - {error}",
            )
            continue

        if not photo_id:
            error = "Missing Pexels photo id"
            unknown.append({"city_id": city.pk, "city": city_name, "error": error})
            _emit_progress(
                progress,
                f"[{position}/{len(records)}] {city_name}: unknown - {error}",
            )
            continue

        try:
            photo = _fetch_pexels_photo(
                photo_id=photo_id,
                api_key=resolved_key,
                http_get=raw_http_get,
            )
        except Exception as exc:
            error = f"Pexels lookup failed: {exc}"
            unknown.append({"city_id": city.pk, "city": city_name, "error": error})
            _emit_progress(
                progress,
                f"[{position}/{len(records)}] {city_name}: unknown - {error}",
            )
            continue

        if _photo_matches_city(photo, item=item):
            matched.append({"city_id": city.pk, "city": city_name, "photo_id": photo_id})
            _emit_progress(
                progress,
                f"[{position}/{len(records)}] {city_name}: match",
            )
            continue

        mismatched_records.append(record)
        _emit_progress(
            progress,
            f"[{position}/{len(records)}] {city_name}: mismatch",
        )

    mismatch_ids = [record["city"].pk for record in mismatched_records]
    _emit_progress(
        progress,
        f"Found {len(mismatch_ids)} mismatched city images to replace",
    )

    replace_image = replace_image or _replace_existing_city_image
    replaced = []
    failed = []
    total = len(mismatched_records)

    for position, record in enumerate(mismatched_records, start=1):
        city = record["city"]
        city_name = getattr(city, "name", "")
        preferred_time = "night" if record.get("is_night") else "day"

        _emit_progress(
            progress,
            f"[{position}/{total}] {city_name}: searching Pexels ({preferred_time})",
        )

        result = replace_image(
            city.pk,
            preferred_time=preferred_time,
            api_key=resolved_key,
            http_get=raw_http_get,
            city_model=city_model,
            catalogue=catalogue,
            used_photo_ids=used_photo_ids,
            used_hashes=used_hashes,
        )

        if result.get("status") == "imported":
            provider_photo_id = _clean(result.get("provider_photo_id"))
            content_sha256 = _clean(result.get("content_sha256"))
            if provider_photo_id:
                used_photo_ids.add(provider_photo_id)
            if content_sha256:
                used_hashes.add(content_sha256)
            replaced.append(
                {
                    "city_id": city.pk,
                    "city": city_name,
                    "time_preference": preferred_time,
                }
            )
            _emit_progress(progress, f"[{position}/{total}] {city_name}: replaced")
        else:
            error = result.get("error") or result.get("status")
            failed.append({"city_id": city.pk, "city": city_name, "error": error})
            _emit_progress(
                progress,
                f"[{position}/{total}] {city_name}: failed - {error}",
            )

    return {
        "status": "ok" if not failed and not unknown else "partial",
        "matched": matched,
        "mismatched_city_ids": mismatch_ids,
        "replaced": replaced,
        "failed": failed,
        "unknown": unknown,
    }
