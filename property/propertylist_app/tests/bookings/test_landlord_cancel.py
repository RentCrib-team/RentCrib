import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Booking,
)

User = get_user_model()


@pytest.mark.django_db
def test_landlord_can_cancel_booking():

    landlord = User.objects.create_user(
        username="landlord",
        email="landlord@test.com",
        password="pass12345",
    )

    tenant = User.objects.create_user(
        username="tenant",
        email="tenant@test.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="General",
        active=True,
    )

    room = Room.objects.create(
        title="Room",
        category=category,
        property_owner=landlord,
        price_per_month=500,
    )

    booking = Booking.objects.create(
        room=room,
        user=tenant,
        start=timezone.now() + timedelta(days=2),
        end=timezone.now() + timedelta(days=2, hours=1),
        status=Booking.STATUS_ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(landlord)

    response = client.post(
        f"/api/v1/bookings/{booking.id}/suspend/"
    )

    assert response.status_code == 200