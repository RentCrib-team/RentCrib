from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import AvailabilitySlot, Booking, Room


pytestmark = pytest.mark.django_db


def _set_room_state(room, *, status, is_available, paid_until):
    Room.objects.filter(pk=room.pk).update(
        status=status,
        is_available=is_available,
        paid_until=paid_until,
    )
    room.refresh_from_db()
    return room


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.parametrize(
    "room_status,is_available,paid_offset_days",
    [
        (Room.Lifecycle.DRAFT, True, 7),
        (Room.Lifecycle.ACTIVE, False, 7),
        (Room.Lifecycle.ACTIVE, True, None),
        (Room.Lifecycle.ACTIVE, True, -1),
    ],
)
def test_all_direct_booking_creation_paths_reject_non_bookable_rooms(
    user_factory,
    room_factory,
    room_status,
    is_available,
    paid_offset_days,
):
    owner = user_factory(username=f"eligibility_owner_{room_status}_{paid_offset_days}")
    seeker = user_factory(username=f"eligibility_seeker_{room_status}_{paid_offset_days}")
    room = room_factory(property_owner=owner)

    today = timezone.localdate()
    paid_until = None if paid_offset_days is None else today + timedelta(days=paid_offset_days)
    _set_room_state(
        room,
        status=room_status,
        is_available=is_available,
        paid_until=paid_until,
    )

    client = _client_for(seeker)
    start = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=1)

    preflight = client.post(
        reverse("v1:booking-create"),
        {
            "room": room.id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        format="json",
    )
    assert preflight.status_code == 400, preflight.data

    legacy = client.post(
        reverse("v1:create-viewing-booking"),
        {
            "room_id": room.id,
            "start": start.isoformat(),
        },
        format="json",
    )
    assert legacy.status_code == 400, legacy.data

    canonical = client.post(
        reverse("v1:bookings-list-create"),
        {
            "room": room.id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        format="json",
    )
    assert canonical.status_code == 400, canonical.data

    assert Booking.objects.filter(room=room).count() == 0


def test_slot_booking_paths_reject_slot_for_unavailable_room(
    user_factory,
    room_factory,
):
    owner = user_factory(username="eligibility_slot_owner")
    seeker = user_factory(username="eligibility_slot_seeker")
    room = room_factory(property_owner=owner)

    _set_room_state(
        room,
        status=Room.Lifecycle.ACTIVE,
        is_available=False,
        paid_until=timezone.localdate() + timedelta(days=7),
    )

    start = (timezone.now() + timedelta(days=3)).replace(microsecond=0)
    slot = AvailabilitySlot.objects.create(
        room=room,
        start=start,
        end=start + timedelta(hours=1),
        max_bookings=1,
    )

    client = _client_for(seeker)

    legacy = client.post(
        reverse("v1:create-viewing-booking"),
        {"slot_id": slot.id},
        format="json",
    )
    assert legacy.status_code == 400, legacy.data

    canonical = client.post(
        reverse("v1:bookings-list-create"),
        {"slot": slot.id},
        format="json",
    )
    assert canonical.status_code == 400, canonical.data

    assert Booking.objects.filter(room=room).count() == 0


def test_canonical_booking_still_accepts_active_available_paid_room(
    user_factory,
    room_factory,
):
    owner = user_factory(username="eligibility_valid_owner")
    seeker = user_factory(username="eligibility_valid_seeker")
    room = room_factory(property_owner=owner)

    _set_room_state(
        room,
        status=Room.Lifecycle.ACTIVE,
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=7),
    )

    start = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=1)

    client = _client_for(seeker)
    response = client.post(
        reverse("v1:bookings-list-create"),
        {
            "room": room.id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Booking.objects.filter(room=room, user=seeker).count() == 1
