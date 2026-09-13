import html
import json
import re
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps
from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone


ENWIKI_API_URL = "https://en.wikipedia.org/w/api.php"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
PROVENANCE_PREFIX = "city_image_provenance"
USER_AGENT = "RentCrib/1.0 (https://rentcrib.co.uk; team@rentcrib.co.uk)"

PAGE_TITLE_OVERRIDES = {
    "bath": "Bath, Somerset",
    "brighton-hove": "Brighton and Hove",
    "durham": "Durham, England",
    "kingston-upon-hull": "Kingston upon Hull",
    "newcastle-upon-tyne": "Newcastle upon Tyne",
    "southend-on-sea": "Southend-on-Sea",
    "stoke-on-trent": "Stoke-on-Trent",
    "wells": "Wells, Somerset",
    "westminster": "City of Westminster",
    "bangor-northern-ireland": "Bangor, County Down",
    "londonderry": "Derry",
    "perth": "Perth, Scotland",
    "bangor-wales": "Bangor, Gwynedd",
    "newport": "Newport, Wales",
}

ACCEPTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
}


def _clean(value):
    return str(value or "").strip()


def _runtime_dependencies():
    from propertylist_app.data.uk_cities import OFFICIAL_UK_CITIES
    from propertylist_app.services.city_images import prepare_city_image

    city_model = apps.get_model("propertylist_app", "City")
    return city_model, OFFICIAL_UK_CITIES, prepare_city_image


def _catalogue_by_slug(catalogue):
    return {
        _clean(item.get("slug")).lower(): item
        for item in catalogue
        if _clean(item.get("slug"))
    }


def _strip_markup(value):
    text = html.unescape(_clean(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _meta_value(extmetadata, key):
    raw = (extmetadata or {}).get(key) or {}
    if isinstance(raw, dict):
        return _strip_markup(raw.get("value"))
    return _strip_markup(raw)


def _license_permits_clean_card(license_name):
    normalised = re.sub(r"\s+", " ", _clean(license_name)).upper()
    return normalised.startswith("CC0") or "PUBLIC DOMAIN" in normalised


def _request_json(http_get, url, params):
    response = http_get(
        url,
        headers={"User-Agent": USER_AGENT},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json() or {}


def _article_title(item):
    slug = _clean(item.get("slug")).lower()
    display_name = _clean(item.get("display_name") or item.get("name"))
    return PAGE_TITLE_OVERRIDES.get(slug, display_name)


def _pageimage_file_names(*, item, http_get):
    title = _article_title(item)
    payload = _request_json(
        http_get,
        ENWIKI_API_URL,
        {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
            "prop": "pageimages",
            "titles": title,
            "piprop": "name|thumbnail",
            "pilicense": "free",
            "pithumbsize": 1600,
        },
    )
    names = []
    for page in ((payload.get("query") or {}).get("pages") or []):
        name = _clean(page.get("pageimage"))
        if name:
            names.append((name, _clean(page.get("title")) or title))
    return names


def _imageinfo_candidate(*, api_url, file_name, page_title, http_get):
    payload = _request_json(
        http_get,
        api_url,
        {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "imageinfo",
            "titles": f"File:{file_name}",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1600,
            "iiextmetadatalanguage": "en",
            "iiextmetadatafilter": (
                "LicenseShortName|LicenseUrl|Artist|Credit|UsageTerms|AttributionRequired"
            ),
        },
    )
    pages = (payload.get("query") or {}).get("pages") or []
    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = _clean(info.get("mime")).lower()
        if mime not in ACCEPTED_MIME_TYPES:
            continue
        ext = info.get("extmetadata") or {}
        license_name = _meta_value(ext, "LicenseShortName") or _meta_value(ext, "UsageTerms")
        if not _license_permits_clean_card(license_name):
            continue
        artist = _meta_value(ext, "Artist") or "Wikimedia Commons contributor"
        credit = _meta_value(ext, "Credit") or artist
        return {
            "file_name": file_name,
            "page_title": page_title,
            "download_url": _clean(info.get("thumburl") or info.get("url")),
            "source_url": _clean(info.get("descriptionurl")),
            "license_name": license_name,
            "license_url": _meta_value(ext, "LicenseUrl"),
            "artist": artist,
            "credit": credit,
            "mime": mime,
        }
    return None


def _commons_search_candidates(*, item, http_get):
    display_name = _clean(item.get("display_name") or item.get("name"))
    nation = _clean(item.get("nation"))
    queries = [
        f"{display_name} {nation} city skyline",
        f"{display_name} {nation} city centre",
        f"{display_name} {nation} United Kingdom",
    ]
    for query in queries:
        payload = _request_json(
            http_get,
            COMMONS_API_URL,
            {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "search",
                "gsrnamespace": 6,
                "gsrsearch": query,
                "gsrlimit": 10,
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": 1600,
                "iiextmetadatalanguage": "en",
                "iiextmetadatafilter": (
                    "LicenseShortName|LicenseUrl|Artist|Credit|UsageTerms|AttributionRequired"
                ),
            },
        )
        for page in ((payload.get("query") or {}).get("pages") or []):
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = _clean(info.get("mime")).lower()
            if mime not in ACCEPTED_MIME_TYPES:
                continue
            ext = info.get("extmetadata") or {}
            license_name = _meta_value(ext, "LicenseShortName") or _meta_value(ext, "UsageTerms")
            if not _license_permits_clean_card(license_name):
                continue
            title = _clean(page.get("title"))
            file_name = title[5:] if title.lower().startswith("file:") else title
            artist = _meta_value(ext, "Artist") or "Wikimedia Commons contributor"
            credit = _meta_value(ext, "Credit") or artist
            download_url = _clean(info.get("thumburl") or info.get("url"))
            if not download_url:
                continue
            yield {
                "file_name": file_name,
                "page_title": _article_title(item),
                "download_url": download_url,
                "source_url": _clean(info.get("descriptionurl")),
                "license_name": license_name,
                "license_url": _meta_value(ext, "LicenseUrl"),
                "artist": artist,
                "credit": credit,
                "mime": mime,
                "search_query": query,
            }


def _resolve_candidate(*, item, http_get):
    errors = []
    try:
        for file_name, page_title in _pageimage_file_names(item=item, http_get=http_get):
            for api_url in (COMMONS_API_URL, ENWIKI_API_URL):
                try:
                    candidate = _imageinfo_candidate(
                        api_url=api_url,
                        file_name=file_name,
                        page_title=page_title,
                        http_get=http_get,
                    )
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                if candidate and candidate.get("download_url"):
                    candidate["search_query"] = f"Wikipedia page image: {page_title}"
                    return candidate
    except Exception as exc:
        errors.append(str(exc))

    try:
        for candidate in _commons_search_candidates(item=item, http_get=http_get):
            return candidate
    except Exception as exc:
        errors.append(str(exc))

    detail = f": {'; '.join(errors[-3:])}" if errors else ""
    raise RuntimeError(f"No usable free Wikimedia city image found{detail}")


def _normalise_downloaded_image(*, content, slug, candidate):
    try:
        with Image.open(BytesIO(content)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            width, height = source.size
            if width < 640 or height < 360:
                raise ValueError(
                    f"source image is too small ({width}x{height}); minimum is 640x360"
                )
            image = ImageOps.fit(
                source,
                (1600, 900),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )

        handle = BytesIO()
        image.save(handle, "JPEG", quality=88, optimize=True, progressive=True)
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


def autofill_city_image(
    city_id,
    *,
    http_get=None,
    city_model=None,
    catalogue=None,
    prepare_image=None,
    atomic_context=None,
    now_func=None,
    replace=False,
):
    """Populate one canonical city image without any external API secret."""

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
    old_image_storage = None
    old_image_name = ""
    slug = ""

    try:
        context = atomic_context() if callable(atomic_context) else nullcontext()
        with context:
            city = city_model.objects.select_for_update().get(pk=city_id)
            slug = _clean(city.slug).lower()
            if city.image and not replace:
                return {"status": "existing", "city_id": city_id, "slug": slug}
            if not getattr(city, "is_active", True):
                return {"status": "inactive", "city_id": city_id, "slug": slug}

            item = catalogue_index.get(slug)
            if item is None:
                raise RuntimeError("City is missing from the official UK catalogue")

            old_image_storage = city.image.storage
            old_image_name = _clean(city.image.name)

            candidate = _resolve_candidate(item=item, http_get=http_get)
            response = http_get(
                candidate["download_url"],
                headers={"User-Agent": USER_AGENT},
                timeout=60,
            )
            response.raise_for_status()
            uploaded = _normalise_downloaded_image(
                content=response.content,
                slug=slug,
                candidate=candidate,
            )
            prepared = prepare_image(uploaded)
            target_name = _prepared_filename(slug, prepared)

            image_storage = city.image.storage
            city.image.save(target_name, prepared, save=False)
            new_image_name = _clean(city.image.name)

            provenance = {
                "city_slug": slug,
                "city_name": _clean(item.get("display_name") or item.get("name") or city.name),
                "provider": "Wikimedia Commons",
                "file_name": candidate["file_name"],
                "wikipedia_page": candidate["page_title"],
                "source_url": candidate["source_url"],
                "license_name": candidate["license_name"],
                "license_url": candidate["license_url"],
                "artist": candidate["artist"],
                "credit": candidate["credit"],
                "visible_attribution_embedded": False,
                "search_query": candidate.get("search_query", ""),
                "stored_image": new_image_name,
                "recorded_at": now_func().isoformat(),
            }
            provenance_name = _save_provenance(image_storage, slug, provenance)

            display_name = _clean(item.get("display_name") or item.get("name"))
            city.image_alt = city.image_alt or f"{display_name} city view"
            city.save(update_fields=["image", "image_alt", "updated_at"])

        if old_image_name and old_image_name != new_image_name:
            _delete_safely(old_image_storage, old_image_name)

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
