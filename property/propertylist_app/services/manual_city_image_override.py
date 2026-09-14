import base64
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path

from django.apps import apps
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from propertylist_app.services.city_image_autofill import PROVENANCE_PREFIX, _clean


MANUAL_CITY_IMAGE_ASSETS = {
    "southampton": {
        "filename": "southampton-user-selected.jpg",
        "parts": (
            "southampton-user-selected.jpg.b64.part1",
            "southampton-user-selected.jpg.b64.part2",
        ),
    },
    "brighton-hove": {
        "filename": "brighton-hove-user-selected.jpg",
        "parts": (
            "brighton-hove-user-selected.jpg.b64.part1",
            "brighton-hove-user-selected.jpg.b64.part2",
            "brighton-hove-user-selected.jpg.b64.part3",
        ),
    },
}


def _runtime_city_model():
    return apps.get_model("propertylist_app", "City")


def _default_asset_root():
    return Path(__file__).resolve().parents[1] / "data" / "manual_city_images"


def _read_asset(*, asset_root, parts):
    encoded = "".join((asset_root / part).read_text(encoding="ascii").strip() for part in parts)
    return base64.b64decode(encoded, validate=True)


def _restore_bytes(storage, name, content):
    if storage.exists(name):
        storage.delete(name)
    if content is not None:
        storage.save(name, ContentFile(content))


def apply_manual_city_images(
    *,
    slugs=None,
    city_model=None,
    asset_root=None,
    atomic_context=None,
    now_func=None,
    progress=None,
):
    """Apply only user-selected city images packaged with this backend fix."""

    city_model = city_model or _runtime_city_model()
    asset_root = Path(asset_root or _default_asset_root())
    atomic_context = atomic_context or transaction.atomic
    now_func = now_func or timezone.now

    selected_slugs = {
        _clean(slug).lower()
        for slug in (slugs if slugs is not None else MANUAL_CITY_IMAGE_ASSETS)
        if _clean(slug)
    }

    replaced = []
    failed = []
    skipped = []

    for slug in sorted(selected_slugs):
        asset = MANUAL_CITY_IMAGE_ASSETS.get(slug)
        if asset is None:
            skipped.append({"slug": slug, "reason": "no packaged manual image"})
            continue

        payload = _read_asset(asset_root=asset_root, parts=asset["parts"])
        content_sha256 = hashlib.sha256(payload).hexdigest()

        image_storage = None
        new_image_name = ""
        old_image_name = ""
        provenance_name = ""
        old_provenance = None

        try:
            context = atomic_context() if callable(atomic_context) else nullcontext()
            with context:
                city = city_model.objects.select_for_update().filter(slug=slug).first()
                if city is None:
                    raise RuntimeError("City not found")

                image_storage = city.image.storage
                old_image_name = _clean(getattr(city.image, "name", ""))
                provenance_name = f"{PROVENANCE_PREFIX}/{slug}.json"
                if image_storage.exists(provenance_name):
                    with image_storage.open(provenance_name, "rb") as handle:
                        old_provenance = handle.read()

                city.image.save(asset["filename"], ContentFile(payload), save=False)
                new_image_name = _clean(city.image.name)
                city.image_is_approved = True
                city.image_alt = f"{city.name} city view"
                city.save(
                    update_fields=[
                        "image",
                        "image_is_approved",
                        "image_alt",
                        "updated_at",
                    ]
                )

                provenance = {
                    "city_slug": slug,
                    "city_name": city.name,
                    "provider": "Manual user selection",
                    "provider_photo_id": "",
                    "content_sha256": content_sha256,
                    "source_url": "",
                    "license_name": "User supplied",
                    "license_url": "",
                    "credit": "User-selected city image",
                    "rights_confirmed": False,
                    "manual_override": True,
                    "stored_image": new_image_name,
                    "recorded_at": now_func().isoformat(),
                }
                _restore_bytes(
                    image_storage,
                    provenance_name,
                    json.dumps(
                        provenance,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ).encode("utf-8"),
                )

            replaced.append(
                {
                    "city_id": city.pk,
                    "city": city.name,
                    "slug": slug,
                    "image": new_image_name,
                    "content_sha256": content_sha256,
                }
            )
            if progress is not None:
                progress(f"{city.name}: manual image applied")
        except Exception as exc:
            if image_storage is not None and new_image_name and new_image_name != old_image_name:
                try:
                    if image_storage.exists(new_image_name):
                        image_storage.delete(new_image_name)
                except Exception:
                    pass
            if image_storage is not None and provenance_name:
                try:
                    _restore_bytes(image_storage, provenance_name, old_provenance)
                except Exception:
                    pass
            failed.append({"slug": slug, "error": str(exc)})
            if progress is not None:
                progress(f"{slug}: failed - {exc}")

    return {
        "status": "ok" if not failed else "partial",
        "replaced": replaced,
        "failed": failed,
        "skipped": skipped,
    }
