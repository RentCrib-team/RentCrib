from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import City, Room, RoomCategorie


@pytest.mark.django_db
def test_city_search_keeps_legacy_null_city_room_visible_until_backfill():
    """Canonical city search must not hide pre-backfill legacy listings."""

    london = City.objects.filter(name__iexact="London").first()
    if london is None:
        london = City.objects.create(name="London")

    manchester = City.objects.filter(name__iexact="Manchester").first()
    if manchester is None:
        manchester = City.objects.create(name="Manchester")

    User = get_user_model()
    legacy_owner = User.objects.create_user(
        username="legacy-null-city-london-owner",
        email="legacy-null-city-london-owner@example.com",
        password="pass123",
    )
    canonical_owner = User.objects.create_user(
        username="canonical-manchester-owner",
        email="canonical-manchester-owner@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Legacy canonical city bridge",
        active=True,
    )
    paid_until = timezone.localdate() + timedelta(days=30)

    Room.objects.create(
        title="Legacy London room",
        category=category,
        price_per_month=800,
        property_owner=legacy_owner,
        status="active",
        is_available=True,
        location="10 Downing Street, London",
        city=None,
        paid_until=paid_until,
    )
    Room.objects.create(
        title="Manchester room on London Road",
        category=category,
        price_per_month=800,
        property_owner=canonical_owner,
        status="active",
        is_available=True,
        location="London Road, Manchester",
        city=manchester,
        paid_until=paid_until,
    )

    response = APIClient().get("/api/v1/search/rooms/", {"city": london.name})

    assert response.status_code == 200
    payload = response.json()
    results = payload.get("results", payload)
    titles = {item["title"] for item in results}

    assert "Legacy London room" in titles
    assert "Manchester room on London Road" not in titles
