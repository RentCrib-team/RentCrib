import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import (
    Room,
    RoomCategorie,
    AvailabilitySlot,
    Booking,
)

User = get_user_model()


def create_room(*, username):
    landlord = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name=f"Cat {username}"[:30],
        active=True,
    )

    return Room.objects.create(
        title=f"Room with synced slots {username}",
        description=(
            "This is a valid room description with enough words to satisfy "
            "the listing validation rules for testing availability slot "
            "generation and booking behaviour."
        ),
        location="SW1A 1AA",
        category=category,
        property_owner=landlord,
        price_per_month=900,
        security_deposit=200,
    )


def update_availability(
    room,
    *,
    mode,
    start_time,
    end_time,
    custom_dates=None,
):
    payload = {
        "view_available_days_mode": mode,
        "availability_from_time": start_time,
        "availability_to_time": end_time,
    }

    if custom_dates is not None:
        payload["view_available_custom_dates"] = custom_dates

    serializer = RoomSerializer(
        room,
        data=payload,
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def local_slot_times(room):
    """
    Return slot boundaries as local HH:MM strings.
    """
    return [
        (
            timezone.localtime(slot.start).strftime("%H:%M"),
            timezone.localtime(slot.end).strftime("%H:%M"),
        )
        for slot in AvailabilitySlot.objects.filter(room=room).order_by("start")
    ]


@pytest.mark.django_db
def test_room_custom_dates_generate_public_booking_slots():
    room = create_room(username="slot_landlord")

    viewing_date = (timezone.localdate() + timedelta(days=5)).isoformat()

    update_availability(
        room,
        mode="custom",
        custom_dates=[viewing_date],
        start_time="09:00",
        end_time="10:00",
    )

    assert AvailabilitySlot.objects.filter(room=room).count() == 2

    client = APIClient()
    url = reverse("v1:room-slots-public", args=[room.id])

    dates_response = client.get(
        url,
        {
            "mode": "dates",
            "only_free": "true",
        },
    )

    assert dates_response.status_code == 200
    assert dates_response.data == {
        "available_dates": [viewing_date],
    }

    slots_response = client.get(
        url,
        {
            "date": viewing_date,
            "only_free": "true",
        },
    )

    assert slots_response.status_code == 200
    assert len(slots_response.data.get("results", [])) == 2


@pytest.mark.django_db
def test_custom_availability_rounds_to_quarter_hour_boundaries():
    """
    09:02-11:08 becomes a usable window of 09:15-11:00.

    The start rounds up to 09:15.
    The end rounds down to 11:00.
    Only complete 30-minute slots that finish by 11:00 are created.
    """
    room = create_room(username="rounding_landlord")

    viewing_date = (
        timezone.localdate() + timedelta(days=5)
    ).isoformat()

    update_availability(
        room,
        mode="custom",
        custom_dates=[viewing_date],
        start_time="09:02",
        end_time="11:08",
    )

    assert local_slot_times(room) == [
        ("09:15", "09:45"),
        ("09:45", "10:15"),
        ("10:15", "10:45"),
    ]

@pytest.mark.django_db
def test_custom_availability_does_not_cross_end_boundary():
    """
    14:13-17:36 becomes a usable window of 14:15-17:30.

    A slot is created only when its full 30 minutes finishes
    on or before 17:30.
    """
    room = create_room(username="end_boundary_landlord")

    viewing_date = (
        timezone.localdate() + timedelta(days=5)
    ).isoformat()

    update_availability(
        room,
        mode="custom",
        custom_dates=[viewing_date],
        start_time="14:13",
        end_time="17:36",
    )

    assert local_slot_times(room) == [
        ("14:15", "14:45"),
        ("14:45", "15:15"),
        ("15:15", "15:45"),
        ("15:45", "16:15"),
        ("16:15", "16:45"),
        ("16:45", "17:15"),
    ]

@pytest.mark.django_db
def test_everyday_mode_generates_slots_for_next_30_days():
    room = create_room(username="everyday_landlord")

    update_availability(
        room,
        mode="everyday",
        start_time="09:00",
        end_time="10:00",
    )

    slots = AvailabilitySlot.objects.filter(room=room)

    # Each complete future day has two 30-minute slots.
    tomorrow = timezone.localdate() + timedelta(days=1)
    final_day = timezone.localdate() + timedelta(days=29)

    future_dates = {
        timezone.localtime(slot.start).date()
        for slot in slots
        if tomorrow <= timezone.localtime(slot.start).date() <= final_day
    }

    expected_dates = {
        timezone.localdate() + timedelta(days=offset)
        for offset in range(1, 30)
    }

    assert future_dates == expected_dates

    for expected_date in expected_dates:
        assert (
            slots.filter(
                start__date=expected_date,
            ).count()
             == 2
        )


@pytest.mark.django_db
def test_weekdays_mode_excludes_saturdays_and_sundays():
    room = create_room(username="weekday_landlord")

    update_availability(
        room,
        mode="weekdays",
        start_time="09:00",
        end_time="09:30",
    )

    tomorrow = timezone.localdate() + timedelta(days=1)
    final_day = timezone.localdate() + timedelta(days=29)

    generated_dates = {
        timezone.localtime(slot.start).date()
        for slot in AvailabilitySlot.objects.filter(room=room)
        if tomorrow <= timezone.localtime(slot.start).date() <= final_day
    }

    expected_dates = {
        timezone.localdate() + timedelta(days=offset)
        for offset in range(1, 30)
        if (
            timezone.localdate() + timedelta(days=offset)
        ).weekday() < 5
    }

    assert generated_dates == expected_dates
    assert all(day.weekday() < 5 for day in generated_dates)


@pytest.mark.django_db
def test_weekends_mode_excludes_mondays_to_fridays():
    room = create_room(username="weekend_landlord")

    update_availability(
        room,
        mode="weekends",
        start_time="09:00",
        end_time="09:30",
    )

    tomorrow = timezone.localdate() + timedelta(days=1)
    final_day = timezone.localdate() + timedelta(days=29)

    generated_dates = {
        timezone.localtime(slot.start).date()
        for slot in AvailabilitySlot.objects.filter(room=room)
        if tomorrow <= timezone.localtime(slot.start).date() <= final_day
    }

    expected_dates = {
        timezone.localdate() + timedelta(days=offset)
        for offset in range(1, 30)
        if (
            timezone.localdate() + timedelta(days=offset)
        ).weekday() >= 5
    }

    assert generated_dates == expected_dates
    assert all(day.weekday() >= 5 for day in generated_dates)


@pytest.mark.django_db
def test_custom_mode_generates_only_selected_future_dates():
    room = create_room(username="custom_dates_landlord")

    first_date = timezone.localdate() + timedelta(days=4)
    second_date = timezone.localdate() + timedelta(days=8)

    update_availability(
        room,
        mode="custom",
        custom_dates=[
            first_date.isoformat(),
            second_date.isoformat(),
        ],
        start_time="12:00",
        end_time="12:30",
    )

    generated_dates = {
        timezone.localtime(slot.start).date()
        for slot in AvailabilitySlot.objects.filter(room=room)
    }

    assert generated_dates == {
        first_date,
        second_date,
    }


@pytest.mark.django_db
def test_sync_removes_obsolete_unbooked_slots_but_preserves_booked_slot():
    room = create_room(username="preserve_booking_landlord")

    tenant = User.objects.create_user(
        username="preserve_booking_tenant",
        email="preserve_booking_tenant@test.com",
        password="pass12345",
    )

    viewing_date = (
        timezone.localdate() + timedelta(days=5)
    ).isoformat()

    update_availability(
        room,
        mode="custom",
        custom_dates=[viewing_date],
        start_time="09:00",
        end_time="11:00",
    )

    original_slots = list(
        AvailabilitySlot.objects.filter(room=room).order_by("start")
    )

    assert len(original_slots) == 4

    booked_slot = original_slots[0]
    obsolete_unbooked_slot = original_slots[1]
    retained_matching_slot_1 = original_slots[2]
    retained_matching_slot_2 = original_slots[3]

    Booking.objects.create(
        user=tenant,
        room=room,
        slot=booked_slot,
        start=booked_slot.start,
        end=booked_slot.end,
    )

    update_availability(
        room,
        mode="custom",
        custom_dates=[viewing_date],
        start_time="10:00",
        end_time="11:00",
    )

    assert AvailabilitySlot.objects.filter(pk=booked_slot.pk).exists()

    assert not AvailabilitySlot.objects.filter(
        pk=obsolete_unbooked_slot.pk,
    ).exists()

    assert AvailabilitySlot.objects.filter(
        pk=retained_matching_slot_1.pk,
    ).exists()

    assert AvailabilitySlot.objects.filter(
        pk=retained_matching_slot_2.pk,
    ).exists()

    assert local_slot_times(room) == [
        ("09:00", "09:30"),
        ("10:00", "10:30"),
        ("10:30", "11:00"),
    ]
    
    
@pytest.mark.django_db
def test_everyday_slots_start_from_future_available_from():
    room = create_room(username="future_everyday_landlord")

    future_start = timezone.localdate() + timedelta(days=10)

    room.available_from = future_start
    room.save(
        update_fields=[
            "available_from",
        ]
    )

    update_availability(
        room,
        mode="everyday",
        start_time="10:00",
        end_time="12:00",
    )

    slots = (
        AvailabilitySlot.objects
        .filter(room=room)
        .order_by("start")
    )

    assert slots.exists()

    first_slot_date = timezone.localtime(
        slots.first().start
    ).date()

    assert first_slot_date == future_start

    assert not any(
        timezone.localtime(slot.start).date() < future_start
        for slot in slots
    )


@pytest.mark.django_db
def test_custom_dates_before_available_from_are_not_generated():
    room = create_room(username="future_custom_landlord")

    available_from = timezone.localdate() + timedelta(days=10)

    before = available_from - timedelta(days=2)
    valid_one = available_from + timedelta(days=1)
    valid_two = available_from + timedelta(days=4)

    room.available_from = available_from
    room.save(
        update_fields=[
            "available_from",
        ]
    )

    update_availability(
        room,
        mode="custom",
        custom_dates=[
            before.isoformat(),
            valid_one.isoformat(),
            valid_two.isoformat(),
        ],
        start_time="10:00",
        end_time="12:00",
    )

    slot_dates = {
        timezone.localtime(slot.start).date()
        for slot in AvailabilitySlot.objects.filter(room=room)
    }

    assert before not in slot_dates
    assert valid_one in slot_dates
    assert valid_two in slot_dates


@pytest.mark.django_db
def test_everyday_slots_start_from_future_available_from():
    room = create_room(username="future_everyday_landlord")

    future_start = timezone.localdate() + timedelta(days=10)

    room.available_from = future_start
    room.save(
        update_fields=[
            "available_from",
        ]
    )

    update_availability(
        room,
        mode="everyday",
        start_time="10:00",
        end_time="12:00",
    )

    slots = (
        AvailabilitySlot.objects
        .filter(room=room)
        .order_by("start")
    )

    assert slots.exists()

    first_slot_date = timezone.localtime(
        slots.first().start
    ).date()

    assert first_slot_date == future_start

    assert not any(
        timezone.localtime(slot.start).date() < future_start
        for slot in slots
    )


@pytest.mark.django_db
def test_custom_dates_before_available_from_are_not_generated():
    room = create_room(username="future_custom_landlord")

    available_from = timezone.localdate() + timedelta(days=10)

    before = available_from - timedelta(days=2)
    valid_one = available_from + timedelta(days=1)
    valid_two = available_from + timedelta(days=4)

    room.available_from = available_from
    room.save(
        update_fields=[
            "available_from",
        ]
    )

    update_availability(
        room,
        mode="custom",
        custom_dates=[
            before.isoformat(),
            valid_one.isoformat(),
            valid_two.isoformat(),
        ],
        start_time="10:00",
        end_time="12:00",
    )

    slot_dates = {
        timezone.localtime(slot.start).date()
        for slot in AvailabilitySlot.objects.filter(room=room)
    }

    assert before not in slot_dates
    assert valid_one in slot_dates
    assert valid_two in slot_dates    