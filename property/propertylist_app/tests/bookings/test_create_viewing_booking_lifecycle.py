from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import AvailabilitySlot, Booking, Room, RoomCategorie


User = get_user_model()


def _room_with_users():
    landlord = User.objects.create_user(
        username="viewing-endpoint-landlord",
        email="viewing-endpoint-landlord@test.com",
        password="pass12345",
    )
    seeker = User.objects.create_user(
        username="viewing-endpoint-seeker",
        email="viewing-endpoint-seeker@test.com",
        password="pass12345",
    )
    category = RoomCategorie.objects.create(name="Viewing endpoint", active=True)
    room = Room.objects.create(
        title="Viewing Endpoint Test Room",
        category=category,
        property_owner=landlord,
        price_per_month=650,
    )
    return seeker, room


@pytest.mark.django_db
def test_create_viewing_booking_slot_uses_active_booking_status_and_slot_end():
    seeker, room = _room_with_users()
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(minutes=30)
    slot = AvailabilitySlot.objects.create(room=room, start=start, end=end)

    client = APIClient()
    client.force_authenticate(seeker)

    response = client.post(
        "/api/v1/bookings/viewing/",
        {"slot_id": slot.id},
        format="json",
    )

    assert response.status_code == 200

    booking = Booking.objects.get(user=seeker, room=room)
    assert booking.status == Booking.STATUS_ACTIVE
    assert booking.start == slot.start
    assert booking.end == slot.end


@pytest.mark.django_db
def test_create_viewing_booking_direct_creates_active_30_minute_window():
    seeker, room = _room_with_users()
    start = timezone.now() + timedelta(days=1)

    client = APIClient()
    client.force_authenticate(seeker)

    response = client.post(
        "/api/v1/bookings/viewing/",
        {
            "room_id": room.id,
            "start": start.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 200

    booking = Booking.objects.get(user=seeker, room=room)
    assert booking.status == Booking.STATUS_ACTIVE
    assert booking.start == start
    assert booking.end == start + timedelta(minutes=30)
