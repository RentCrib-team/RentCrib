from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


@pytest.mark.django_db
def test_search_returns_photo_count_without_gallery_urls():
    owner = User.objects.create_user(
        username="search-image-owner",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Search image payload",
        active=True,
    )
    room = Room.objects.create(
        title="Search image payload room",
        description="Room used to verify the lightweight search image payload.",
        price_per_month=900,
        location="Southampton SO14 1AA",
        category=category,
        property_owner=owner,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )

    for index in range(3):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/search-{index}.jpg",
            status=RoomImage.STATUS_APPROVED,
        )

    response = APIClient().get(
        reverse("v1:search-rooms"),
        {"ordering": "-created_at"},
    )

    assert response.status_code == 200
    payload = response.json()
    results = payload.get("results", payload)
    result = next(item for item in results if item["id"] == room.id)

    assert result["photo_count"] == 3
    assert result["cover_image"]
    assert "other_images" not in result
