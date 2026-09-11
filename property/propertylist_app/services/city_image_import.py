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
        raise CityImageImportError(f"{source_type} images require license_url")

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


def _read_manifest(manifest_path):
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

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            raise CityImageImportError(
                "manifest is missing columns: " + ", ".join(sorted(missing_columns))
            )
        return [
            (row_number, row)
            for row_number, row in enumerate(reader, start=2)
        ]


def _validate_candidate(*, row_number, row, assets_root, replace):
    slug = _clean(row.get("slug")).lower()
    city = City.objects.filter(slug=slug).first()
    if city is None:
        raise CityImageImportError("canonical City record does not exist")

    if city.image and not replace:
        return {
            "status": "existing",
            "row_number": row_number,
            "slug": slug,
        }

    _validate_rights(row)
    source_path = _resolve_asset_path(assets_root, _clean(row.get("filename")))

    # Validate the exact file through the same image pipeline used during apply.
    # The file is deliberately reopened during the write phase so a dry-run has
    # no persistent file handles and apply can be all-or-nothing.
    with source_path.open("rb") as source_handle:
        uploaded = File(source_handle, name=source_path.name)
        prepare_city_image(uploaded)

    return {
        "status": "validated",
        "row_number": row_number,
        "slug": slug,
        "city_id": city.pk,
        "source_path": source_path,
        "image_alt": _clean(row.get("image_alt")),
    }


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

    Apply is deliberately two-phase: every selected row is validated first. If
    any row fails, no image is imported. The write phase then runs inside one
    database transaction and cleans up newly-created storage objects if the
    transaction cannot complete.
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
    validated_items = []

    for row_number, row in _read_manifest(manifest_path):
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

        try:
            candidate = _validate_candidate(
                row_number=row_number,
                row=row,
                assets_root=assets_root,
                replace=replace,
            )
        except Exception as exc:
            result["errors"].append(
                {"row": row_number, "slug": slug, "error": str(exc)}
            )
            continue

        if candidate["status"] == "existing":
            result["existing"] += 1
            continue

        result["validated"] += 1
        validated_items.append(candidate)

    # Validation is a gate: do not partially import a manifest with bad rows.
    if result["errors"] or not apply or not validated_items:
        return result

    created_storage_objects = []
    old_storage_objects = []
    current_item = None

    try:
        with transaction.atomic():
            for item in validated_items:
                current_item = item
                city = City.objects.select_for_update().get(pk=item["city_id"])

                # Re-check the existing-image guard after acquiring the lock.
                if city.image and not replace:
                    result["existing"] += 1
                    result["validated"] -= 1
                    continue

                old_name = city.image.name if city.image else ""
                old_storage = city.image.storage if city.image else None

                source_path = item["source_path"]
                with source_path.open("rb") as source_handle:
                    uploaded = File(source_handle, name=source_path.name)
                    prepared = prepare_city_image(uploaded)
                    target_name = _target_filename(city, prepared, source_path)
                    city.image.save(target_name, prepared, save=False)

                new_name = city.image.name if city.image else ""
                new_storage = city.image.storage if city.image else None
                if new_name:
                    created_storage_objects.append((new_storage, new_name))

                city.image_alt = item["image_alt"] or city.image_alt or city.name
                city.save(update_fields=["image", "image_alt", "updated_at"])

                if old_name and old_name != new_name:
                    old_storage_objects.append((old_storage, old_name))

        # Only after the transaction commits is it safe to remove superseded
        # objects. New images are now the canonical references in the database.
        for storage, name in old_storage_objects:
            _delete_storage_file_safely(storage, name)

        result["imported"] = len(created_storage_objects)
        return result

    except Exception as exc:
        # Database rollback cannot roll back object-storage writes. Delete every
        # new object created by this apply attempt so the failed batch is clean.
        for storage, name in created_storage_objects:
            _delete_storage_file_safely(storage, name)

        result["imported"] = 0
        result["errors"].append(
            {
                "row": (current_item or {}).get("row_number", 0),
                "slug": (current_item or {}).get("slug", ""),
                "error": str(exc),
            }
        )
        return result
