from contextlib import contextmanager

import requests

from propertylist_app.services.city_image_autofill import (
    CITY_MATCH_ALIASES,
    PEXELS_SEARCH_URL,
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

# Exact Pexels photos vetted for the 20 public city-directory cards.
# Southampton and Brighton & Hove are the product owner's manual selections;
# the remaining entries use Pexels pages whose own city/landmark metadata
# identifies the target city.
USER_SELECTED_PEXELS_PHOTO_IDS = {
    "southampton": "19916599",
    "london": "30680312",
    "birmingham": "33175822",
    "manchester": "34760018",
    "liverpool": "12953548",
    "leeds": "16666012",
    "bristol": "24880409",
    "sheffield": "12698033",
    "newcastle-upon-tyne": "34175710",
    "cambridge": "32783000",
    "oxford": "18283322",
    "bath": "32038429",
    "york": "35701057",
    "nottingham": "37228472",
    "leicester": "30890693",
    "coventry": "35751281",
    "exeter": "18218243",
    "lancaster": "36093695",
    "brighton-hove": "9161809",
    "wrexham": "35714326",
}

# Brighton is part of the official Brighton & Hove city entry, while Pexels
# describes the selected image simply as Brighton. This alias applies only
# while this explicit replacement service is running.
USER_SELECTED_MATCH_ALIASES = {
    "brighton-hove": ("Brighton & Hove", "Brighton"),
}


class _SelectedSearchResponse:
    def __init__(self, photo):
        self.status_code = 200
        self._photo = photo

    def json(self):
        return {"photos": [self._photo]}

    def raise_for_status(self):
        return None


def _fetch_photo(*, photo_id, api_key, http_get):
    response = _bounded_http_get(
        http_get,
        PEXELS_PHOTO_URL.format(photo_id=photo_id),
        headers={"Authorization": api_key},
    )
    if response.status_code == 401:
        raise RuntimeError("Pexels API rejected PEXELS_API_KEY")
    response.raise_for_status()
    photo = response.json() or {}
    if _clean(photo.get("id")) != _clean(photo_id):
        raise RuntimeError("Pexels returned an unexpected selected photo id")
    return photo


def _selected_http_get(*, photo, raw_http_get):
    def get(url, **kwargs):
        if url == PEXELS_SEARCH_URL:
            return _SelectedSearchResponse(photo)
        return raw_http_get(url, **kwargs)

    return get


@contextmanager
def _temporary_match_alias(slug):
    aliases = USER_SELECTED_MATCH_ALIASES.get(slug)
    if not aliases:
        yield
        return

    had_existing = slug in CITY_MATCH_ALIASES
    previous = CITY_MATCH_ALIASES.get(slug)
    CITY_MATCH_ALIASES[slug] = aliases
    try:
        yield
    finally:
        if had_existing:
            CITY_MATCH_ALIASES[slug] = previous
        else:
            CITY_MATCH_ALIASES.pop(slug, None)


def apply_user_selected_pexels_city_images(
    *,
    slugs=None,
    city_model=None,
    catalogue=None,
    replace_image=None,
    http_get=None,
    api_key=None,
    progress=None,
):
    """Replace selected public city cards with exact vetted Pexels photos."""

    if city_model is None or catalogue is None:
        runtime_city_model, runtime_catalogue, _ = _runtime_dependencies()
        city_model = city_model or runtime_city_model
        catalogue = catalogue or runtime_catalogue

    resolved_key = _api_key(api_key)
    if not resolved_key:
        return {
            "status": "disabled",
            "replaced": [],
            "failed": [],
            "skipped": [],
            "error": "PEXELS_API_KEY is not configured",
        }

    selected_slugs = {
        _clean(slug).lower()
        for slug in (slugs if slugs is not None else USER_SELECTED_PEXELS_PHOTO_IDS)
        if _clean(slug)
    }
    catalogue_index = _catalogue_by_slug(catalogue)
    raw_http_get = http_get or requests.get
    replace_image = replace_image or _replace_existing_city_image

    all_cities = list(
        city_model.objects.filter(is_active=True, image_is_approved=True)
        .exclude(image="")
        .exclude(image__isnull=True)
        .order_by("display_order", "name", "pk")
    )
    cities = [
        city for city in all_cities if _clean(getattr(city, "slug", "")).lower() in selected_slugs
    ]
    records = _city_image_records(all_cities)
    record_by_id = {record["city"].pk: record for record in records}
    used_photo_ids = {record["photo_id"] for record in records if record["photo_id"]}
    used_hashes = {
        record["content_sha256"] for record in records if record["content_sha256"]
    }

    replaced = []
    failed = []
    skipped = []
    total = len(cities)
    _emit_progress(progress, f"Applying {total} user-selected city images")

    for position, city in enumerate(cities, start=1):
        slug = _clean(city.slug).lower()
        photo_id = _clean(USER_SELECTED_PEXELS_PHOTO_IDS.get(slug))
        item = catalogue_index.get(slug)

        if not photo_id:
            skipped.append({"city_id": city.pk, "city": city.name, "reason": "no selected photo"})
            continue
        if item is None:
            failed.append({"city_id": city.pk, "city": city.name, "error": "City is missing from the official UK catalogue"})
            continue

        try:
            photo = _fetch_photo(
                photo_id=photo_id,
                api_key=resolved_key,
                http_get=raw_http_get,
            )
            with _temporary_match_alias(slug):
                if not _photo_matches_city(photo, item=item):
                    raise RuntimeError("Selected Pexels photo metadata does not match the target city")

                record = record_by_id.get(city.pk) or {}
                preferred_time = "night" if record.get("is_night") else "day"
                result = replace_image(
                    city.pk,
                    preferred_time=preferred_time,
                    api_key=resolved_key,
                    http_get=_selected_http_get(photo=photo, raw_http_get=raw_http_get),
                    city_model=city_model,
                    catalogue=catalogue,
                    used_photo_ids=used_photo_ids,
                    used_hashes=used_hashes,
                )
        except Exception as exc:
            result = {"status": "failed", "error": str(exc)}

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
                    "city": city.name,
                    "provider_photo_id": photo_id,
                }
            )
            _emit_progress(progress, f"[{position}/{total}] {city.name}: replaced with selected Pexels photo {photo_id}")
        else:
            error = result.get("error") or result.get("status")
            failed.append({"city_id": city.pk, "city": city.name, "error": error})
            _emit_progress(progress, f"[{position}/{total}] {city.name}: failed - {error}")

    present_slugs = {_clean(getattr(city, "slug", "")).lower() for city in cities}
    for slug in sorted(selected_slugs.difference(present_slugs)):
        skipped.append({"city_id": None, "city": slug, "reason": "city not eligible or not found"})

    return {
        "status": "ok" if not failed else "partial",
        "replaced": replaced,
        "failed": failed,
        "skipped": skipped,
    }
