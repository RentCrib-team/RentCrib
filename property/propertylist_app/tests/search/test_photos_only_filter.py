import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


def extract_results(response):
    """
    Support both the standard RentCrib response envelope and a direct
    paginated/list response.
    """
    payload = response.data

    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]

    return payload


def create_active_room(*, owner, category, title, legacy_image=None):
    return Room.objects.create(
        title=title,
        category=category,
        price_per_month=800,
        property_owner=owner,
        image=legacy_image,
        status="active",
        paid_until=timezone.now().date() + timedelta(days=30),
    )


@pytest.mark.django_db
def test_search_photos_only_returns_only_rooms_with_approved_photos():
    cache.clear()

    owner = User.objects.create_user(
        username="photo_filter_owner",
        password="pass123",
        email="photo-filter-owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Photo Filter",
        active=True,
    )

    create_active_room(
        owner=owner,
        category=category,
        title="NoPhotos",
    )

    create_active_room(
        owner=owner,
        category=category,
        title="LegacyPhoto",
        legacy_image="rooms/legacy.jpg",
    )

    pending_room = create_active_room(
        owner=owner,
        category=category,
        title="PendingPhoto",
    )
    RoomImage.objects.create(
        room=pending_room,
        image="rooms/pending.jpg",
        status="pending",
    )

    rejected_room = create_active_room(
        owner=owner,
        category=category,
        title="RejectedPhoto",
    )
    RoomImage.objects.create(
        room=rejected_room,
        image="rooms/rejected.jpg",
        status="rejected",
    )

    approved_room = create_active_room(
        owner=owner,
        category=category,
        title="ApprovedPhoto",
    )
    RoomImage.objects.create(
        room=approved_room,
        image="rooms/approved.jpg",
        status="approved",
    )

    response = APIClient().get(
        reverse("v1:search-rooms"),
        {"photos_only": "true"},
    )

    assert response.status_code == 200, response.data

    results = extract_results(response)
    titles = {item["title"] for item in results}

    assert "NoPhotos" not in titles
    assert "LegacyPhoto" not in titles
    assert "PendingPhoto" not in titles
    assert "RejectedPhoto" not in titles
    assert "ApprovedPhoto" in titles


@pytest.mark.django_db
def test_public_search_main_photo_exposes_only_approved_room_images():
    cache.clear()

    owner = User.objects.create_user(
        username="main_photo_owner",
        password="pass123",
        email="main-photo-owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Main Photo Moderation",
        active=True,
    )

    legacy_room = create_active_room(
        owner=owner,
        category=category,
        title="Legacy Main Photo",
        legacy_image="rooms/legacy-main.jpg",
    )

    pending_room = create_active_room(
        owner=owner,
        category=category,
        title="Pending Main Photo",
    )
    RoomImage.objects.create(
        room=pending_room,
        image="rooms/pending-main.jpg",
        status="pending",
    )

    rejected_room = create_active_room(
        owner=owner,
        category=category,
        title="Rejected Main Photo",
    )
    RoomImage.objects.create(
        room=rejected_room,
        image="rooms/rejected-main.jpg",
        status="rejected",
    )

    approved_room = create_active_room(
        owner=owner,
        category=category,
        title="Approved Main Photo",
    )
    RoomImage.objects.create(
        room=approved_room,
        image="rooms/approved-main.jpg",
        status="approved",
    )

    response = APIClient().get(
        reverse("v1:search-rooms"),
        {"q": "Main Photo"},
    )

    assert response.status_code == 200, response.data

    results = extract_results(response)
    rooms_by_id = {item["id"]: item for item in results}

    assert rooms_by_id[legacy_room.id]["main_photo"] is None
    assert rooms_by_id[legacy_room.id]["photo_count"] == 0

    assert rooms_by_id[pending_room.id]["main_photo"] is None
    assert rooms_by_id[pending_room.id]["photo_count"] == 0

    assert rooms_by_id[rejected_room.id]["main_photo"] is None
    assert rooms_by_id[rejected_room.id]["photo_count"] == 0

    approved_main_photo = rooms_by_id[approved_room.id]["main_photo"]

    assert approved_main_photo is not None
    assert approved_main_photo.endswith("/media/rooms/approved-main.jpg")
    assert rooms_by_id[approved_room.id]["photo_count"] == 1