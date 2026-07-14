import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


@pytest.mark.django_db
def test_search_photos_only_returns_rooms_with_legacy_or_approved_photos():
    owner = User.objects.create_user(
        username="o1",
        password="pass123",
        email="o1@example.com",
    )
    cat = RoomCategorie.objects.create(name="Any", active=True)
    paid_until = timezone.now().date() + timedelta(days=30)

    # Room A: no legacy image + no RoomImage => should NOT return
    Room.objects.create(
        title="NoPhotos",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        paid_until=paid_until,
    )

    # Room B: has legacy image => should return
    Room.objects.create(
        title="LegacyPhoto",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        image="rooms/x.jpg",
        paid_until=paid_until,
    )

    # Room C: has RoomImage approved => should return
    r_img = Room.objects.create(
        title="ApprovedPhoto",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        paid_until=paid_until,
    )
    RoomImage.objects.create(
        room=r_img,
        image="rooms/y.jpg",
        status="approved",
    )

    url = reverse("v1:search-rooms")
    res = APIClient().get(url, {"photos_only": "true"})
    assert res.status_code == 200
    results = res.data.get("results", res.data)
    titles = {x["title"] for x in results}

    assert "NoPhotos" not in titles
    assert "LegacyPhoto" in titles
    assert "ApprovedPhoto" in titles