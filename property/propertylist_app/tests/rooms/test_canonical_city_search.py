from datetime import timedelta

import pytest
from django.utils import timezone

from propertylist_app.models import City, Room, RoomCategorie
from propertylist_app.services.city_assignment import backfill_room_cities


SEARCH_URL = "/api/v1/search/rooms/"
ROOMS_URL = "/api/v1/rooms/"


def _results(response):
    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload.get("data"), dict) and isinstance(
        payload["data"].get("results"), list
    ):
        return payload["data"]["results"]
    return payload.get("results", [])


def _room_create_payload(category, city_id):
    return {
        "category_id": category.id,
        "title": "Canonical city listing",
        "description": (
            "This is a canonical city listing with enough descriptive words to "
            "satisfy the listing validation rules while keeping the test focused "
            "on assigning the room to a normalized city record in the backend."
        ),
        "property_type": "flat",
        "location": "10 Test Street, Southampton, SO14 1AA",
        "price_per_month": "750.00",
        "is_available": True,
        "city": city_id,
    }


@pytest.mark.django_db
def test_room_create_accepts_canonical_city_foreign_key(auth_client):
    city = City.objects.create(name="Southampton")
    category = RoomCategorie.objects.create(
        name="City Assignment",
        key="city-assignment",
        slug="city-assignment",
        active=True,
    )

    response = auth_client.post(
        ROOMS_URL,
        _room_create_payload(category, city.id),
        format="json",
    )

    assert response.status_code == 201, response.data
    room_id = response.data["data"]["id"]
    room = Room.objects.get(pk=room_id)
    assert room.city_id == city.id


@pytest.mark.django_db
def test_room_create_rejects_nonexistent_city_foreign_key(auth_client):
    category = RoomCategorie.objects.create(
        name="Invalid City Assignment",
        key="invalid-city-assignment",
        slug="invalid-city-assignment",
        active=True,
    )

    response = auth_client.post(
        ROOMS_URL,
        _room_create_payload(category, 99999999),
        format="json",
    )

    assert response.status_code == 400
    assert not Room.objects.filter(title="Canonical city listing").exists()


@pytest.mark.django_db
def test_city_search_uses_room_city_relation_not_address_text(
    api_client,
    room_factory,
    user_factory,
):
    london = City.objects.create(name="London")
    manchester = City.objects.create(name="Manchester")
    today = timezone.localdate()

    london_owner = user_factory(
        username="london-search-owner",
        email="london-search-owner@example.com",
    )
    manchester_owner = user_factory(
        username="manchester-search-owner",
        email="manchester-search-owner@example.com",
    )

    room_factory(
        property_owner=london_owner,
        title="Canonical London room",
        location="2 Main Street, KA6 7QL",
        city=london,
        status="active",
        is_available=True,
        paid_until=today + timedelta(days=10),
    )
    room_factory(
        property_owner=manchester_owner,
        title="Manchester room on London Road",
        location="London Road, Manchester, M1 1AA",
        city=manchester,
        status="active",
        is_available=True,
        paid_until=today + timedelta(days=10),
    )

    response = api_client.get(SEARCH_URL, {"city": "london"})

    assert response.status_code == 200
    titles = [room["title"] for room in _results(response)]
    assert titles == ["Canonical London room"]


@pytest.mark.django_db
def test_city_search_accepts_exact_city_name_and_hides_inactive_city(
    api_client,
    room_factory,
    user_factory,
):
    bristol = City.objects.create(name="Bristol")
    hidden = City.objects.create(name="Hidden City", is_active=False)
    today = timezone.localdate()

    room_factory(
        property_owner=user_factory(
            username="bristol-search-owner",
            email="bristol-search-owner@example.com",
        ),
        title="Bristol canonical room",
        city=bristol,
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=True,
    )
    room_factory(
        property_owner=user_factory(
            username="hidden-city-search-owner",
            email="hidden-city-search-owner@example.com",
        ),
        title="Inactive city room",
        city=hidden,
        paid_until=today + timedelta(days=10),
        status="active",
        is_available=True,
    )

    response = api_client.get(SEARCH_URL, {"city": "Bristol"})
    assert response.status_code == 200
    assert [room["title"] for room in _results(response)] == [
        "Bristol canonical room"
    ]

    hidden_response = api_client.get(SEARCH_URL, {"city": hidden.slug})
    assert hidden_response.status_code == 200
    assert _results(hidden_response) == []


@pytest.mark.django_db
def test_legacy_room_city_backfill_only_applies_unambiguous_matches(
    room_factory,
    user_factory,
):
    london = City.objects.create(name="London")
    southampton = City.objects.create(name="Southampton")

    london_room = room_factory(
        property_owner=user_factory(
            username="legacy-london-owner",
            email="legacy-london-owner@example.com",
        ),
        title="Legacy London room",
        location="10 Downing Street, Westminster, London, SW1A 2AA",
        city=None,
    )
    southampton_room = room_factory(
        property_owner=user_factory(
            username="legacy-southampton-owner",
            email="legacy-southampton-owner@example.com",
        ),
        title="London Road Southampton room",
        location="London Road, Southampton, SO14 1AA",
        city=None,
    )
    unknown_room = room_factory(
        property_owner=user_factory(
            username="legacy-unknown-owner",
            email="legacy-unknown-owner@example.com",
        ),
        title="Postcode only room",
        location="SW1A 1AA",
        city=None,
    )

    dry_run = backfill_room_cities(apply=False)
    assert dry_run == {
        "scanned": 3,
        "matched": 2,
        "updated": 0,
        "unmatched": 1,
    }

    london_room.refresh_from_db()
    southampton_room.refresh_from_db()
    unknown_room.refresh_from_db()
    assert london_room.city_id is None
    assert southampton_room.city_id is None
    assert unknown_room.city_id is None

    applied = backfill_room_cities(apply=True)
    assert applied["updated"] == 2

    london_room.refresh_from_db()
    southampton_room.refresh_from_db()
    unknown_room.refresh_from_db()
    assert london_room.city_id == london.id
    assert southampton_room.city_id == southampton.id
    assert unknown_room.city_id is None
