from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    LandlordVerificationRequest,
    Room,
    RoomCategorie,
    UserProfile,
)


pytestmark = pytest.mark.django_db


def make_user(username, role="landlord", advertiser_verified=False):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.advertiser_verified = advertiser_verified
    profile.save(update_fields=["role", "advertiser_verified"])

    return user


def make_room(owner, title):
    category = RoomCategorie.objects.create(
        name="Room Test",
        active=True,
    )

    return Room.objects.create(
        title=title,
        description="A clean and well maintained room close to transport links.",
        price_per_month=750,
        security_deposit=500,
        available_from=timezone.localdate() + timedelta(days=7),
        is_available=True,
        status="active",
        paid_until=timezone.localdate() + timedelta(days=30),
        category=category,
        property_owner=owner,
        property_type="flat",
        location="SW1A 1AA",
    )


def unwrap(response):
    payload = response.data
    return payload.get("data", payload)


def test_unverified_landlord_room_returns_landlord_verified_false():
    landlord = make_user("badge_unverified_landlord", advertiser_verified=False)
    room = make_room(landlord, "Unverified Landlord Badge Room")

    client = APIClient()
    response = client.get(f"/api/v1/rooms/{room.id}/")

    assert response.status_code == 200, response.data

    data = unwrap(response)

    assert data["landlord_verified"] is False


def test_approved_landlord_room_returns_landlord_verified_true():
    landlord = make_user("badge_approved_landlord", advertiser_verified=False)
    room = make_room(landlord, "Approved Landlord Badge Room")

    verification_request = LandlordVerificationRequest.objects.create(
        user=landlord,
        status=LandlordVerificationRequest.STATUS_APPROVED,
        reviewed_at=timezone.now(),
    )

    landlord.profile.advertiser_verified = True
    landlord.profile.save(update_fields=["advertiser_verified"])

    client = APIClient()
    response = client.get(f"/api/v1/rooms/{room.id}/")

    assert response.status_code == 200, response.data

    data = unwrap(response)

    assert verification_request.status == LandlordVerificationRequest.STATUS_APPROVED
    assert data["landlord_verified"] is True


def test_verified_advertisers_only_returns_only_verified_landlords():
    verified_landlord = make_user("search_verified_landlord", advertiser_verified=True)
    unverified_landlord = make_user("search_unverified_landlord", advertiser_verified=False)

    verified_room = make_room(verified_landlord, "Verified Search Room")
    unverified_room = make_room(unverified_landlord, "Unverified Search Room")

    client = APIClient()
    response = client.get("/api/v1/search/rooms/?verified_advertisers_only=true")

    assert response.status_code == 200, response.data

    data = unwrap(response)
    room_ids = {item["id"] for item in data}

    assert verified_room.id in room_ids
    assert unverified_room.id not in room_ids