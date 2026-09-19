from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


@pytest.mark.django_db
def test_compact_search_returns_card_fields_once(django_user_model):
    cache.clear()
    owner = django_user_model.objects.create_user(
        username="compact-owner",
        email="compact-owner@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(name="Compact", active=True)
    room = Room.objects.create(
        title="Compact result",
        description="Detail-only text that must not inflate room cards.",
        location="Southampton SO14 0AA",
        price_per_month=750,
        security_deposit=750,
        property_owner=owner,
        category=category,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )
    for index in range(3):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/original-{index}.webp",
            thumbnail=f"room_images/thumbnails/card-{index}.webp",
            status=RoomImage.STATUS_APPROVED,
        )

    response = APIClient().get(
        reverse("v1:search-rooms"),
        {"compact": "1", "limit": 20},
    )

    assert response.status_code == 200
    assert set(response.data) == {"ok", "message", "data", "meta"}
    assert "results" not in response.data
    card = response.data["data"][0]
    assert card["cover_image"].endswith("card-0.webp")
    assert card["photo_count"] == 3
    assert "description" not in card
    assert "other_images" not in card


@pytest.mark.django_db
def test_legacy_search_envelope_remains_compatible(django_user_model):
    cache.clear()
    response = APIClient().get(reverse("v1:search-rooms"))
    assert response.status_code == 200
    assert "data" in response.data
    assert "results" in response.data
