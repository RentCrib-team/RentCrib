import pytest

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Booking,
    MessageThread,
)


User = get_user_model()


@pytest.mark.django_db
def test_booking_reschedule_snapshots_thread_roles():
    landlord = User.objects.create_user(
        username="reschedule-landlord",
        email="reschedule-landlord@test.com",
        password="pass12345",
    )
    seeker = User.objects.create_user(
        username="reschedule-seeker",
        email="reschedule-seeker@test.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="General",
        active=True,
    )

    room = Room.objects.create(
        title="Reschedule Test Room",
        category=category,
        property_owner=landlord,
        price_per_month=500,
    )

    original_start = timezone.now() + timedelta(days=2)
    original_end = original_start + timedelta(hours=1)

    booking = Booking.objects.create(
        room=room,
        user=seeker,
        start=original_start,
        end=original_end,
        status=Booking.STATUS_ACTIVE,
    )

    new_start = timezone.now() + timedelta(days=3)
    new_end = new_start + timedelta(hours=1)

    client = APIClient()
    client.force_authenticate(seeker)

    response = client.patch(
        f"/api/v1/bookings/{booking.id}/reschedule/",
        {
            "start": new_start.isoformat(),
            "end": new_end.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 200

    thread = (
        MessageThread.objects
        .filter(room=room)
        .filter(participants=landlord)
        .filter(participants=seeker)
        .distinct()
        .get()
    )

    assert thread.landlord_id == landlord.id
    assert thread.seeker_id == seeker.id