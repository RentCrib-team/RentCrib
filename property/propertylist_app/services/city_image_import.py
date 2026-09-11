import csv
from pathlib import Path

from django.core.files import File
from django.db import transaction

from propertylist_app.models import City
from propertylist_app.services.city_images import prepare_city_image


ALLOWED_SOURCE_TYPES = {
    "rentcrib_owned",
    "commissioned",
    "licensed_stock",
    "public_domain",
    "cc0",
    "cc_by",
    "cc_by_sa",
}
THIRD_PARTY_SOURCE_TYPES = {
    "licensed_stock",
    "public_domain",
    "cc0",
    "cc_by",
    "cc_by_sa",
}
LICENSE_LINK_REQUIRED_SOURCE_TYPES = {
    "public_domain",
    "cc0",
    "cc_by",
    "cc_by_sa",
}
CREDIT_REQUIRED_SOURCE_TYPES = {"cc_by", "cc_by_sa"}
TRUTHY = {"1", "true", "yes", "y"}


class CityImageImportError(ValueError):
    pass


def _clean(value):
    return str(value or "").strip()


def _rights_confirmed(value):
    return _clean(value).lower() in TRUTHY


def _resolve_asset_path(assets_root, filename):
    root = Path(assets_root).resolve()
    relative = Path(filename)

    if relative.is_absolute():
        raise CityImageImportError("filename must be relative to the assets root")

    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise CityImageImportError("filename escapes the configured assets root")
    if not resolved.is_file():
        raise CityImageImportError(f"asset file does not exist: {filename}")

    return resolved


def _validate_rights(row):
    source_type = _clean(row.get("source_type")).lower()
    source_url = _clean(row.get("source_url"))
    license_name = _clean(row.get("license_name"))
    license_url = _clean(row.get("license_url"))
    credit = _clean(row.get("credit"))

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise CityImageImportError(
            "source_type must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_TYPES))
        )

    if not _rights_confirmed(row.get("rights_confirmed")):
        raise CityImageImportError(
            "rights_confirmed must be yes/true/1 before an image can be imported"
        )

    if source_type in THIRD_PARTY_SOURCE_TYPES and not source_url:
        raise CityImageImportError("third-party images require source_url")

    if source_type in THIRD_PARTY_SOURCE_TYPES and not license_name:
        raise CityImageImportError("third-party images require license_name")

    if source_type in LICENSE_LINK_REQUIRED_SOURCE_TYPES and not license_url:
        raise CityImageImportError(
            f"{source_type} images require license_url"
        )

    if source_type in CREDIT_REQUIRED_SOURCE_TYPES and not credit:
        raise CityImageImportError(
            f"{source_type} images require photographer/creator credit"
        )


def _target_filename(city, prepared_file, source_path):
    prepared_name = _clean(getattr(prepared_file, "name", ""))
    suffix = Path(prepared_name).suffix.lower()
    if not suffix:
        suffix = source_path.suffix.lower()
    if not suffix:
        suffix = ".jpg"
    return f"{city.slug}{suffix}"


def _delete_storage_file_safely(storage, name):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:
        pass


def import_city_images(
    *,
    manifest_path,
    assets_root,
    apply=False,
    replace=False,
    only_slugs=None,
):
    """Validate and optionally import approved city-card images.

    The manifest is the source-control audit record for image provenance and
    commercial-use approval. Blank filename rows are treated as pending work.
    Nothing is written unless apply=True.
    """

    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise CityImageImportError(f"manifest does not exist: {manifest_path}")

    selected_slugs = {
        _clean(slug).lower() for slug in (only_slugs or []) if _clean(slug)
    }

    result = {
        "rows": 0,
        "pending": 0,
        "existing": 0,
        "validated": 0,
        "imported": 0,
        "errors": [],
    }

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {
            "slug",
            "filename",
            "image_alt",
            "source_type",
            "source_name",
            "source_url",
            "license_name",
            "license_url",
            "credit",
            "rights_confirmed",
        }
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            raise CityImageImportError(
                "manifest is missing columns: " + ", ".join(sorted(missing_columns))
            )

        for row_number, row in enumerate(reader, start=2):
            slug = _clean(row.get("slug")).lower()
            if not slug:
                result["errors"].append(
                    {"row": row_number, "slug": "", "error": "slug is required"}
                )
                continue

            if selected_slugs and slug not in selected_slugs:
                continue

            result["rows"] += 1
            filename = _clean(row.get("filename"))
            if not filename:
                result["pending"] += 1
                continue

            city = City.objects.filter(slug=slug).first()
            if city is None:
                result["errors"].append(
                    {
                        "row": row_number,
                        "slug": slug,
                        "error": "canonical City record does not exist",
                    }
                )
                continue

            if city.image and not replace:
                result["existing"] += 1
                continue

            try:
                _validate_rights(row)
                source_path = _resolve_asset_path(assets_root, filename)

                with source_path.open("rb") as source_handle:
                    uploaded = File(source_handle, name=source_path.name)
                    prepared = prepare_city_image(uploaded)
                    result["validated"] += 1

                    if not apply:
                        continue

                    old_name = city.image.name if city.image else ""
                    old_storage = city.image.storage if city.image else None
                    target_name = _target_filename(city, prepared, source_path)
                    image_alt = _clean(row.get("image_alt")) or city.image_alt or city.name

                    try:
                        with transaction.atomic():
                            city.image.save(target_name, prepared, save=False)
                            city.image_alt = image_alt
                            city.save(update_fields=["image", "image_alt", "updated_at"])
                            new_name = city.image.name if city.image else ""

                            if old_name and old_name != new_name:
                                transaction.on_commit(
                                    lambda storage=old_storage, name=old_name: (
                                        _delete_storage_file_safely(storage, name)
                                    )
                                )
                    except Exception:
                        # If storage accepted the new object but the DB write failed,
                        # remove that new object so the import does not leak media.
                        try:
                            if city.image and city.image.name != old_name:
                                city.image.storage.delete(city.image.name)
                        except Exception:
                            pass
                        raise

                    result["imported"] += 1

            except Exception as exc:
                result["errors"].append(
                    {
                        "row": row_number,
                        "slug": slug,
                        "error": str(exc),
                    }
                )

    return result
