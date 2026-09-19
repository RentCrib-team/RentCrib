from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Room, RoomCategorie, UserProfile


def _create_room(*, owner, category):
    return Room.objects.create(
        title="Avatar Room",
        description="",
        price_per_month=Decimal("750"),
        location="",
        category=category,
        property_owner=owner,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        avg_rating=4.0,
    )


@pytest.mark.django_db
def test_landlord_viewings_includes_seeker_avatar_directly_on_booking_row():
    landlord = User.objects.create_user(
        username="landlord_avatar",
        email="landlord-avatar@example.com",
        password="pass12345",
    )
    seeker = User.objects.create_user(
        username="seeker_avatar",
        email="seeker-avatar@example.com",
        password="pass12345",
    )

    profile, _ = UserProfile.objects.get_or_create(user=seeker)
    profile.avatar = "avatars/seeker.jpg"
    profile.save(update_fields=["avatar"])

    category = RoomCategorie.objects.create(
        name="Avatar Central",
        active=True,
    )
    room = _create_room(owner=landlord, category=category)

    now = timezone.now()
    booking = Booking.objects.create(
        user=seeker,
        room=room,
        start=now + timedelta(days=1),
        end=now + timedelta(days=1, hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.get(reverse("v1:landlord-viewings-list"))

    assert response.status_code == 200

    returned_booking = next(
        item
        for item in response.data["results"]
        if item["id"] == booking.id
    )

    assert returned_booking["user_id"] == seeker.id
    assert returned_booking["seeker_avatar"]
    assert returned_booking["seeker_avatar"].endswith(
        "/media/avatars/seeker.jpg"
    )
    assert returned_booking["seeker_avatar"].startswith(
        "http://testserver/"
    )
