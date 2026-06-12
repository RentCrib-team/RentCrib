from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_nearby_orders_by_distance_and_attaches_distance(monkeypatch):
    """
    GET /api/rooms/nearby/?postcode=...&radius_miles=...
    - Sorted by distance ascending
    - Each item has distance_miles
    """
    def fake_geocode(_postcode):
        return (51.5074, -0.1278)  # London

    monkeypatch.setattr(
        "propertylist_app.api.views.public.geocode_postcode_cached",
        fake_geocode,
    )

    owner = User.objects.create_user(
        username="o",
        password="pass123",
        email="o@example.com",
    )
    cat = RoomCategorie.objects.create(name="Any", active=True)
    paid_until = timezone.now().date() + timedelta(days=30)

    Room.objects.create(
        title="Near",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        latitude=51.51,
        longitude=-0.10,
        paid_until=paid_until,
    )
    Room.objects.create(
        title="Mid",
        category=cat,
        price_per_month=850,
        property_owner=owner,
        latitude=51.60,
        longitude=-0.20,
        paid_until=paid_until,
    )
    Room.objects.create(
        title="Far",
        category=cat,
        price_per_month=900,
        property_owner=owner,
        latitude=52.00,
        longitude=0.00,
        paid_until=paid_until,
    )

    client = APIClient()
    url = reverse("v1:rooms-nearby")
    response = client.get(url, {"postcode": "SW1A 1AA", "radius_miles": 200})

    assert response.status_code == 200, response.data

    payload = response.data
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    results = payload.get("results", payload) if isinstance(payload, dict) else payload

    titles = [item["title"] for item in results[:3]]
    assert titles == ["Near", "Mid", "Far"]

    for item in results[:3]:
        assert item.get("distance_miles") is not None

    distances = [item.get("distance_miles") for item in results[:3]]
    assert all(isinstance(distance, (int, float)) for distance in distances)
    assert distances[0] <= distances[1] <= distances[2]


@pytest.mark.django_db
def test_search_with_postcode_distance_ordering_and_reverse(monkeypatch):
    """
    GET /api/search/rooms/?postcode=...&ordering=distance_miles|-distance_miles
    - Respects distance ordering both directions
    """
    def fake_geocode(_postcode):
        return (51.5074, -0.1278)  # London

    monkeypatch.setattr(
        "propertylist_app.api.views.public.geocode_postcode_cached",
        fake_geocode,
    )

    owner = User.objects.create_user(
        username="o2",
        password="pass123",
        email="o2@example.com",
    )
    cat = RoomCategorie.objects.create(name="Any2", active=True)
    paid_until = timezone.now().date() + timedelta(days=30)

    Room.objects.create(
        title="Near",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        latitude=51.51,
        longitude=-0.10,
        paid_until=paid_until,
    )
    Room.objects.create(
        title="Mid",
        category=cat,
        price_per_month=850,
        property_owner=owner,
        latitude=51.60,
        longitude=-0.20,
        paid_until=paid_until,
    )
    Room.objects.create(
        title="Far",
        category=cat,
        price_per_month=900,
        property_owner=owner,
        latitude=52.00,
        longitude=0.00,
        paid_until=paid_until,
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    response_ascending = client.get(
        url,
        {
            "postcode": "SW1A 1AA",
            "radius_miles": 200,
            "ordering": "distance_miles",
        },
    )
    assert response_ascending.status_code == 200, response_ascending.data

    payload_ascending = response_ascending.data
    if (
        isinstance(payload_ascending, dict)
        and payload_ascending.get("ok") is True
        and "data" in payload_ascending
    ):
        payload_ascending = payload_ascending["data"]

    results_ascending = (
        payload_ascending.get("results", payload_ascending)
        if isinstance(payload_ascending, dict)
        else payload_ascending
    )

    titles_ascending = [item["title"] for item in results_ascending[:3]]
    assert titles_ascending == ["Near", "Mid", "Far"]

    response_descending = client.get(
        url,
        {
            "postcode": "SW1A 1AA",
            "radius_miles": 200,
            "ordering": "-distance_miles",
        },
    )
    assert response_descending.status_code == 200, response_descending.data

    payload_descending = response_descending.data
    if (
        isinstance(payload_descending, dict)
        and payload_descending.get("ok") is True
        and "data" in payload_descending
    ):
        payload_descending = payload_descending["data"]

    results_descending = (
        payload_descending.get("results", payload_descending)
        if isinstance(payload_descending, dict)
        else payload_descending
    )

    titles_descending = [item["title"] for item in results_descending[:3]]
    assert titles_descending == ["Far", "Mid", "Near"]