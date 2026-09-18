from contextlib import contextmanager

import requests

from propertylist_app.services.city_image_autofill import (
    CITY_MATCH_ALIASES,
    PEXELS_SEARCH_URL,
    _api_key,
    _catalogue_by_slug,
    _clean,
    _download_url,
    _match_text,
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

PUBLIC_CITYSCAPE_SLUGS = (
    "london",
    "birmingham",
    "glasgow",
    "leeds",
    "edinburgh",
    "liverpool",
    "sheffield",
    "manchester",
    "bristol",
    "leicester",
    "cardiff",
    "belfast",
    "coventry",
    "bradford",
    "nottingham",
    "newcastle-upon-tyne",
    "brighton-hove",
    "derby",
    "kingston-upon-hull",
    "plymouth",
)

# Pexels photos whose own metadata describes a broad cityscape/skyline rather
# than a single isolated building. Cities without a pinned photo are resolved
# at runtime through the same strict broad-cityscape gate below.
USER_SELECTED_PEXELS_PHOTO_IDS = {
    "london": "16435133",
    "birmingham": "9450535",
    "glasgow": "10569132",
    "leeds": "16666012",
    "edinburgh": "28851814",
    "liverpool": "13436004",
    "sheffield": "12698033",
    "manchester": "6585361",
    "bristol": "17574496",
    "cardiff": "37499335",
    "belfast": "15955120",
    "nottingham": "26289338",
    "newcastle-upon-tyne": "2893285",
    "brighton-hove": "37153111",
    "derby": "34719040",
    "kingston-upon-hull": "5321464",
    "plymouth": "10834188",
}

# Brighton is the city name used by Pexels for the official Brighton & Hove
# catalogue entry. Other special-name aliases already live in CITY_MATCH_ALIASES.
USER_SELECTED_MATCH_ALIASES = {
    "brighton-hove": ("Brighton & Hove", "Brighton"),
}

BROAD_CITYSCAPE_TERMS = (
    "aerial view",
    "cityscape",
    "city skyline",
    "skyline",
    "panoramic",
    "panorama",
    "city center",
    "city centre",
    "downtown",
    "urban landscape",
    "city overview",
    "city view",
    "rooftops",
    "street scene",
)

ISOLATED_SUBJECT_TERMS = (
    "single building",
    "building facade",
    "building exterior",
    "cathedral",
    "castle",
    "memorial",
    "stadium",
    "observation tower",
    "interior",
    "close up",
    "close-up",
)


class _SelectedSearchResponse:
    def __init__(self, photo):
        self.status_code = 200
        self._photo = photo

    def json(self):
        return {"photos": [self._photo]}

    def raise_for_status(self):
        return None


def _photo_cityscape_text(photo):
    return _match_text(
        " ".join(
            value
            for value in (
                _clean(photo.get("alt")),
                _clean(photo.get("url")),
            )
            if value
        )
    )


def _photo_is_broad_cityscape(photo):
    """Reject isolated-building imagery even when it belongs to the right city."""

    text = _photo_cityscape_text(photo)
    if not text:
        return False

    has_broad_context = any(
        _match_text(term) in text for term in BROAD_CITYSCAPE_TERMS
    )
    if not has_broad_context:
        return False

    # Isolated landmarks are allowed only when the metadata also describes
    # unmistakable whole-city context such as a skyline, panorama or cityscape.
    if any(_match_text(term) in text for term in ISOLATED_SUBJECT_TERMS):
        return any(
            _match_text(term) in text
            for term in (
                "cityscape",
                "city skyline",
                "skyline",
                "panoramic",
                "panorama",
                "urban landscape",
                "city overview",
                "rooftops",
            )
        )

    return True


def _cityscape_queries(item):
    display_name = _clean(item.get("display_name") or item.get("name"))
    nation = _clean(item.get("nation"))
    return (
        f"{display_name} {nation} United Kingdom aerial cityscape skyline".strip(),
        f"{display_name} {nation} United Kingdom city centre panorama".strip(),
        f"{display_name} {nation} United Kingdom urban skyline".strip(),
    )


def _cityscape_score(photo):
    text = _photo_cityscape_text(photo)
    score = 0

    for term, weight in (
        ("aerial view", 8),
        ("cityscape", 8),
        ("city skyline", 8),
        ("skyline", 6),
        ("panoramic", 6),
        ("panorama", 6),
        ("city center", 5),
        ("city centre", 5),
        ("urban landscape", 5),
        ("city overview", 5),
        ("rooftops", 3),
        ("street scene", 2),
    ):
        if _match_text(term) in text:
            score += weight

    width = photo.get("width") or 0
    height = photo.get("height") or 0
    if width and height and width >= height:
        score += 4
    if width and height and width >= 1200 and height >= 675:
        score += 3

    return score


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


def _search_broad_cityscape_photo(
    *,
    item,
    api_key,
    http_get,
    excluded_photo_ids=None,
):
    excluded_photo_ids = {
        _clean(value) for value in (excluded_photo_ids or ()) if _clean(value)
    }
    candidates = {}

    for query_index, query in enumerate(_cityscape_queries(item)):
        response = _bounded_http_get(
            http_get,
            PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "orientation": "landscape",
                "size": "large",
                "per_page": 15,
                "page": 1,
            },
        )
        if response.status_code == 401:
            raise RuntimeError("Pexels API rejected PEXELS_API_KEY")
        response.raise_for_status()

        for result_index, photo in enumerate(
            (response.json() or {}).get("photos") or []
        ):
            photo_id = _clean(photo.get("id"))
            if (
                not photo_id
                or photo_id in excluded_photo_ids
                or not _download_url(photo)
                or not _photo_matches_city(photo, item=item)
                or not _photo_is_broad_cityscape(photo)
            ):
                continue

            candidate = (
                _cityscape_score(photo),
                -query_index,
                -result_index,
                photo,
            )
            current = candidates.get(photo_id)
            if current is None or candidate[:3] > current[:3]:
                candidates[photo_id] = candidate

    if not candidates:
        raise RuntimeError(
            "Pexels returned no unused broad cityscape photo for the target city"
        )

    return max(candidates.values(), key=lambda candidate: candidate[:3])[3]


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
    """Replace public city cards with broad cityscape/skyline Pexels photos."""

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
        for slug in (slugs if slugs is not None else PUBLIC_CITYSCAPE_SLUGS)
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
        city
        for city in all_cities
        if _clean(getattr(city, "slug", "")).lower() in selected_slugs
    ]
    records = _city_image_records(all_cities)
    record_by_id = {record["city"].pk: record for record in records}
    photo_id_by_city = {
        record["city"].pk: _clean(record.get("photo_id")) for record in records
    }
    content_hash_by_city = {
        record["city"].pk: _clean(record.get("content_sha256"))
        for record in records
    }

    replaced = []
    failed = []
    skipped = []
    total = len(cities)
    _emit_progress(progress, f"Applying {total} broad public city images")

    for position, city in enumerate(cities, start=1):
        slug = _clean(city.slug).lower()
        item = catalogue_index.get(slug)

        if item is None:
            failed.append(
                {
                    "city_id": city.pk,
                    "city": city.name,
                    "error": "City is missing from the official UK catalogue",
                }
            )
            continue

        used_photo_ids = {
            value
            for city_id, value in photo_id_by_city.items()
            if city_id != city.pk and value
        }
        used_hashes = {
            value
            for city_id, value in content_hash_by_city.items()
            if city_id != city.pk and value
        }

        try:
            with _temporary_match_alias(slug):
                pinned_photo_id = _clean(
                    USER_SELECTED_PEXELS_PHOTO_IDS.get(slug)
                )
                if pinned_photo_id:
                    photo = _fetch_photo(
                        photo_id=pinned_photo_id,
                        api_key=resolved_key,
                        http_get=raw_http_get,
                    )
                else:
                    photo = _search_broad_cityscape_photo(
                        item=item,
                        api_key=resolved_key,
                        http_get=raw_http_get,
                        excluded_photo_ids=used_photo_ids,
                    )

                if not _photo_matches_city(photo, item=item):
                    raise RuntimeError(
                        "Selected Pexels photo metadata does not match the target city"
                    )
                if not _photo_is_broad_cityscape(photo):
                    raise RuntimeError(
                        "Selected Pexels photo is not a broad cityscape/skyline scene"
                    )

                record = record_by_id.get(city.pk) or {}
                preferred_time = "night" if record.get("is_night") else "day"
                result = replace_image(
                    city.pk,
                    preferred_time=preferred_time,
                    api_key=resolved_key,
                    http_get=_selected_http_get(
                        photo=photo,
                        raw_http_get=raw_http_get,
                    ),
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
            photo_id_by_city[city.pk] = provider_photo_id
            content_hash_by_city[city.pk] = content_sha256
            replaced.append(
                {
                    "city_id": city.pk,
                    "city": city.name,
                    "provider_photo_id": provider_photo_id,
                }
            )
            _emit_progress(
                progress,
                f"[{position}/{total}] {city.name}: replaced with broad cityscape photo {provider_photo_id}",
            )
        else:
            error = result.get("error") or result.get("status")
            failed.append(
                {
                    "city_id": city.pk,
                    "city": city.name,
                    "error": error,
                }
            )
            _emit_progress(
                progress,
                f"[{position}/{total}] {city.name}: failed - {error}",
            )

    present_slugs = {
        _clean(getattr(city, "slug", "")).lower() for city in cities
    }
    for slug in sorted(selected_slugs.difference(present_slugs)):
        skipped.append(
            {
                "city_id": None,
                "city": slug,
                "reason": "city not eligible or not found",
            }
        )

    return {
        "status": "ok" if not failed else "partial",
        "replaced": replaced,
        "failed": failed,
        "skipped": skipped,
    }
