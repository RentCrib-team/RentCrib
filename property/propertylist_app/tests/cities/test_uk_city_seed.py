import importlib

import pytest

from propertylist_app.data.uk_cities import (
    BANGOR_SLUGS,
    OFFICIAL_UK_CITIES,
    OFFICIAL_UK_CITY_COUNT,
)
from propertylist_app.models import City
from propertylist_app.services.uk_city_catalogue import seed_official_uk_cities


CITIES_URL = "/api/v1/cities/"


def test_official_uk_city_dataset_has_complete_unique_slug_set():
    assert OFFICIAL_UK_CITY_COUNT == 76
    assert len(OFFICIAL_UK_CITIES) == OFFICIAL_UK_CITY_COUNT

    slugs = [item["slug"] for item in OFFICIAL_UK_CITIES]
    assert len(slugs) == len(set(slugs))

    nation_counts = {}
    for item in OFFICIAL_UK_CITIES:
        nation_counts[item["nation"]] = nation_counts.get(item["nation"], 0) + 1

    assert nation_counts == {
        "England": 55,
        "Northern Ireland": 6,
        "Scotland": 8,
        "Wales": 7,
    }


def test_migration_0100_freezes_the_same_76_city_slug_set():
    migration = importlib.import_module(
        "propertylist_app.migrations.0100_seed_official_uk_cities"
    )
    frozen_slugs = {item[1] for item in migration.SEEDED_UK_CITIES}
    runtime_slugs = {item["slug"] for item in OFFICIAL_UK_CITIES}

    assert len(migration.SEEDED_UK_CITIES) == OFFICIAL_UK_CITY_COUNT == 76
    assert frozen_slugs == runtime_slugs


@pytest.mark.django_db
def test_seed_creates_all_official_uk_cities_and_features_southampton():
    City.objects.all().delete()

    result = seed_official_uk_cities()

    assert result == {
        "expected": 76,
        "created": 76,
        "existing": 0,
        "total": 76,
    }
    assert City.objects.count() == 76

    southampton = City.objects.get(slug="southampton")
    assert southampton.name == "Southampton"
    assert southampton.is_active is True
    assert southampton.is_featured is True
    assert southampton.display_order == 1
    assert southampton.image_alt == "Southampton"

    london = City.objects.get(slug="london")
    assert london.name == "London"
    assert london.is_active is True
    assert london.is_featured is False

    assert set(
        City.objects.filter(slug__in=BANGOR_SLUGS).values_list("slug", flat=True)
    ) == BANGOR_SLUGS


@pytest.mark.django_db
def test_seed_is_idempotent_and_does_not_overwrite_admin_city_controls():
    City.objects.all().delete()
    seed_official_uk_cities()

    london = City.objects.get(slug="london")
    london.is_active = False
    london.is_featured = True
    london.display_order = 7
    london.image_alt = "Admin controlled London image"
    london.save(
        update_fields=[
            "is_active",
            "is_featured",
            "display_order",
            "image_alt",
        ]
    )

    result = seed_official_uk_cities()

    assert result["created"] == 0
    assert result["existing"] == 76
    assert result["total"] == 76
    assert City.objects.count() == 76

    london.refresh_from_db()
    assert london.is_active is False
    assert london.is_featured is True
    assert london.display_order == 7
    assert london.image_alt == "Admin controlled London image"


@pytest.mark.django_db
def test_public_city_api_keeps_bangor_cards_city_name_only(api_client):
    City.objects.all().delete()
    seed_official_uk_cities()

    response = api_client.get(CITIES_URL, {"q": "Bangor", "limit": 100})

    assert response.status_code == 200
    bangors = response.data["data"]
    assert len(bangors) == 2
    assert {city["name"] for city in bangors} == {"Bangor"}
    assert {city["slug"] for city in bangors} == BANGOR_SLUGS
    assert all(city["image_alt"] == "Bangor" for city in bangors)
