from datetime import timedelta

import pytest
from django.utils import timezone

from propertylist_app.models import City


CITIES_URL = "/api/v1/cities/"
HOME_URL = "/api/v1/home/"


@pytest.mark.django_db
def test_public_cities_are_canonical_and_never_derived_from_room_location(
    api_client,
    room_factory,
):
    london = City.objects.create(
        name="London",
        is_active=True,
        display_order=2,
    )
    City.objects.create(
        name="Bristol",
        is_active=True,
        display_order=1,
    )
    City.objects.create(
        name="Hidden City",
        is_active=False,
        display_order=0,
    )

    room_factory(
        title="Canonical London room",
        location="2 Main Street, KA6 7QL",
        city=london,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=7),
    )

    response = api_client.get(CITIES_URL)

    assert response.status_code == 200
    names = [city["name"] for city in response.data["data"]]
    assert names == ["Bristol", "London"]
    assert "2 Main Street, KA6 7QL" not in names
    assert "Hidden City" not in names

    london_payload = next(
        city for city in response.data["data"] if city["name"] == "London"
    )
    assert london_payload["slug"] == "london"
    assert london_payload["image"] is None
    assert london_payload["image_alt"] == "London"
    assert london_payload["room_count"] == 1


@pytest.mark.django_db
def test_public_city_room_count_only_counts_discoverable_rooms(
    api_client,
    room_factory,
):
    city = City.objects.create(name="Manchester")
    today = timezone.localdate()

    room_factory(
        title="Live Manchester room",
        city=city,
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=True,
    )
    room_factory(
        title="Unavailable Manchester room",
        city=city,
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=False,
    )
    room_factory(
        title="Expired Manchester room",
        city=city,
        paid_until=today - timedelta(days=1),
        status="active",
        is_available=True,
    )
    room_factory(
        title="Unpaid Manchester room",
        city=city,
        paid_until=None,
        status="active",
        is_available=True,
    )

    response = api_client.get(CITIES_URL)

    assert response.status_code == 200
    assert response.data["data"][0]["name"] == "Manchester"
    assert response.data["data"][0]["room_count"] == 1


@pytest.mark.django_db
def test_public_city_search_filters_city_name_not_property_address(
    api_client,
    room_factory,
):
    london = City.objects.create(name="London")
    City.objects.create(name="Bristol")

    room_factory(
        title="Odd address room",
        city=london,
        location="Manchester Road, London, SW1A 1AA",
        paid_until=timezone.localdate() + timedelta(days=10),
    )

    response = api_client.get(CITIES_URL, {"q": "Manch"})

    assert response.status_code == 200
    assert response.data["data"] == []


@pytest.mark.django_db
def test_homepage_uses_only_active_featured_canonical_cities_in_admin_order(
    api_client,
    room_factory,
):
    southampton = City.objects.create(
        name="Southampton",
        is_active=True,
        is_featured=True,
        display_order=1,
    )
    leeds = City.objects.create(
        name="Leeds",
        is_active=True,
        is_featured=True,
        display_order=2,
    )
    City.objects.create(
        name="Bristol",
        is_active=True,
        is_featured=False,
        display_order=0,
    )
    City.objects.create(
        name="Inactive Featured",
        is_active=False,
        is_featured=True,
        display_order=0,
    )

    today = timezone.localdate()
    room_factory(
        title="Southampton live room",
        city=southampton,
        location="99 Completely Different Address, SO14 1AA",
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=True,
    )
    room_factory(
        title="Leeds live room",
        city=leeds,
        location="2 Main Street, KA6 7QL",
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=True,
    )

    response = api_client.get(HOME_URL)

    assert response.status_code == 200
    cities = response.data["data"]["popular_cities"]
    assert [city["name"] for city in cities] == ["Southampton", "Leeds"]
    assert [city["room_count"] for city in cities] == [1, 1]
    assert all("KA6 7QL" not in city["name"] for city in cities)
