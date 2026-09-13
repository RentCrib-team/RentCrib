import csv
from io import BytesIO

import pytest
from django.conf import settings
from django.test import override_settings
from PIL import Image

from propertylist_app.data.uk_cities import OFFICIAL_UK_CITIES
from propertylist_app.models import City
from propertylist_app.services.city_image_import import import_city_images


def _write_jpeg(path, *, width=1600, height=900):
    output = BytesIO()
    Image.new("RGB", (width, height), (110, 125, 140)).save(
        output,
        format="JPEG",
        quality=90,
    )
    path.write_bytes(output.getvalue())


def _write_manifest(path, rows):
    fieldnames = [
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
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_repository_city_image_manifest_covers_all_official_cities():
    manifest = (
        settings.BASE_DIR
        / "propertylist_app"
        / "data"
        / "city_image_manifest.csv"
    )
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == len(OFFICIAL_UK_CITIES) == 76
    assert rows[0]["slug"] == "southampton"
    assert {row["slug"] for row in rows} == {
        item["slug"] for item in OFFICIAL_UK_CITIES
    }


@pytest.mark.django_db
def test_city_image_import_is_dry_run_by_default(tmp_path):
    City.objects.all().delete()
    city = City.objects.create(name="Southampton")

    assets = tmp_path / "assets"
    assets.mkdir()
    _write_jpeg(assets / "southampton.jpg")

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "southampton",
                "filename": "southampton.jpg",
                "image_alt": "Southampton waterfront skyline",
                "source_type": "rentcrib_owned",
                "source_name": "RentCrib",
                "source_url": "",
                "license_name": "",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "yes",
            }
        ],
    )

    result = import_city_images(
        manifest_path=manifest,
        assets_root=assets,
        apply=False,
    )

    assert result == {
        "rows": 1,
        "pending": 0,
        "existing": 0,
        "validated": 1,
        "imported": 0,
        "errors": [],
    }
    city.refresh_from_db()
    assert not city.image


@pytest.mark.django_db(transaction=True)
def test_city_image_import_applies_to_managed_storage(tmp_path):
    City.objects.all().delete()
    city = City.objects.create(name="Southampton")

    assets = tmp_path / "assets"
    assets.mkdir()
    _write_jpeg(assets / "southampton.jpg")

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "southampton",
                "filename": "southampton.jpg",
                "image_alt": "Southampton waterfront skyline",
                "source_type": "rentcrib_owned",
                "source_name": "RentCrib",
                "source_url": "",
                "license_name": "",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "true",
            }
        ],
    )

    media_root = tmp_path / "media"
    with override_settings(MEDIA_ROOT=media_root):
        result = import_city_images(
            manifest_path=manifest,
            assets_root=assets,
            apply=True,
        )

        assert result["validated"] == 1
        assert result["imported"] == 1
        assert result["errors"] == []

        city.refresh_from_db()
        assert city.image
        assert city.image_alt == "Southampton waterfront skyline"
        assert city.image.storage.exists(city.image.name)


@pytest.mark.django_db
def test_city_image_import_rejects_unconfirmed_rights(tmp_path):
    City.objects.all().delete()
    city = City.objects.create(name="London")

    assets = tmp_path / "assets"
    assets.mkdir()
    _write_jpeg(assets / "london.jpg")

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "london",
                "filename": "london.jpg",
                "image_alt": "London skyline",
                "source_type": "licensed_stock",
                "source_name": "Example stock provider",
                "source_url": "https://example.com/photo",
                "license_name": "Commercial licence",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "no",
            }
        ],
    )

    result = import_city_images(
        manifest_path=manifest,
        assets_root=assets,
        apply=True,
    )

    assert result["imported"] == 0
    assert len(result["errors"]) == 1
    assert "rights_confirmed" in result["errors"][0]["error"]
    city.refresh_from_db()
    assert not city.image


@pytest.mark.django_db
def test_city_image_import_rejects_path_traversal(tmp_path):
    City.objects.all().delete()
    city = City.objects.create(name="Bristol")

    assets = tmp_path / "assets"
    assets.mkdir()
    outside = tmp_path / "outside.jpg"
    _write_jpeg(outside)

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "bristol",
                "filename": "../outside.jpg",
                "image_alt": "Bristol skyline",
                "source_type": "rentcrib_owned",
                "source_name": "RentCrib",
                "source_url": "",
                "license_name": "",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "yes",
            }
        ],
    )

    result = import_city_images(
        manifest_path=manifest,
        assets_root=assets,
        apply=True,
    )

    assert result["imported"] == 0
    assert len(result["errors"]) == 1
    assert "assets root" in result["errors"][0]["error"]
    city.refresh_from_db()
    assert not city.image


@pytest.mark.django_db
def test_blank_manifest_rows_are_pending_not_errors(tmp_path):
    City.objects.all().delete()
    City.objects.create(name="Manchester")

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "manchester",
                "filename": "",
                "image_alt": "Manchester",
                "source_type": "",
                "source_name": "",
                "source_url": "",
                "license_name": "",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "",
            }
        ],
    )

    result = import_city_images(
        manifest_path=manifest,
        assets_root=tmp_path / "assets",
        apply=False,
    )

    assert result["rows"] == 1
    assert result["pending"] == 1
    assert result["errors"] == []


@pytest.mark.django_db(transaction=True)
def test_city_image_apply_imports_nothing_if_any_selected_row_fails_validation(tmp_path):
    City.objects.all().delete()
    southampton = City.objects.create(name="Southampton")
    london = City.objects.create(name="London")

    assets = tmp_path / "assets"
    assets.mkdir()
    _write_jpeg(assets / "southampton.jpg")
    _write_jpeg(assets / "london.jpg")

    manifest = tmp_path / "manifest.csv"
    _write_manifest(
        manifest,
        [
            {
                "slug": "southampton",
                "filename": "southampton.jpg",
                "image_alt": "Southampton waterfront skyline",
                "source_type": "rentcrib_owned",
                "source_name": "RentCrib",
                "source_url": "",
                "license_name": "",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "yes",
            },
            {
                "slug": "london",
                "filename": "london.jpg",
                "image_alt": "London skyline",
                "source_type": "licensed_stock",
                "source_name": "Example stock provider",
                "source_url": "https://example.com/photo",
                "license_name": "Commercial licence",
                "license_url": "",
                "credit": "",
                "rights_confirmed": "no",
            },
        ],
    )

    media_root = tmp_path / "media"
    with override_settings(MEDIA_ROOT=media_root):
        result = import_city_images(
            manifest_path=manifest,
            assets_root=assets,
            apply=True,
        )

    assert result["validated"] == 1
    assert result["imported"] == 0
    assert len(result["errors"]) == 1

    southampton.refresh_from_db()
    london.refresh_from_db()
    assert not southampton.image
    assert not london.image
