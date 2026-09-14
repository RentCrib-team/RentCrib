"""Query optimization for room availability slot synchronization."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import AvailabilitySlot, Booking


_INSTALLED = False


def _optimized_sync_availability_slots(self, room):
    """Synchronize viewing slots without one booking query per slot."""

    def round_up_to_quarter(value):
        total_minutes = (value.hour * 60) + value.minute
        if value.second or value.microsecond:
            total_minutes += 1
        return ((total_minutes + 14) // 15) * 15

    def round_down_to_quarter(value):
        total_minutes = (value.hour * 60) + value.minute
        return (total_minutes // 15) * 15

    mode = room.view_available_days_mode
    start_time = room.availability_from_time
    end_time = room.availability_to_time

    valid_modes = {
        "everyday",
        "weekdays",
        "weekends",
        "custom",
    }

    if mode not in valid_modes:
        return

    if not start_time or not end_time:
        return

    slot_minutes = 30
    today = timezone.localdate()
    available_from = getattr(room, "available_from", None)
    start_date = max(today, available_from or today)

    desired_dates = []

    if mode == "custom":
        for selected_date in room.view_available_custom_dates or []:
            if isinstance(selected_date, str):
                try:
                    selected_date = datetime.fromisoformat(selected_date).date()
                except (TypeError, ValueError):
                    continue

            if selected_date >= start_date:
                desired_dates.append(selected_date)
    else:
        for day_offset in range(30):
            selected_date = start_date + timedelta(days=day_offset)

            if mode == "weekdays" and selected_date.weekday() >= 5:
                continue

            if mode == "weekends" and selected_date.weekday() < 5:
                continue

            desired_dates.append(selected_date)

    desired_slots = []
    start_minutes = round_up_to_quarter(start_time)
    end_minutes = round_down_to_quarter(end_time)

    if end_minutes <= start_minutes:
        return

    for selected_date in desired_dates:
        day_start = datetime.combine(selected_date, time.min)
        rounded_start = day_start + timedelta(minutes=start_minutes)
        rounded_end = day_start + timedelta(minutes=end_minutes)

        if timezone.is_naive(rounded_start):
            rounded_start = timezone.make_aware(
                rounded_start,
                timezone.get_current_timezone(),
            )

        if timezone.is_naive(rounded_end):
            rounded_end = timezone.make_aware(
                rounded_end,
                timezone.get_current_timezone(),
            )

        current = rounded_start

        while True:
            slot_end = current + timedelta(minutes=slot_minutes)

            if slot_end > rounded_end:
                break

            if slot_end > timezone.now():
                desired_slots.append((current, slot_end))

            current = slot_end

    desired_set = set(desired_slots)

    future_slots = list(
        AvailabilitySlot.objects.filter(
            room=room,
            end__gt=timezone.now(),
        )
    )

    future_slot_ids = [slot.id for slot in future_slots]
    booked_slot_ids = set(
        Booking.objects.filter(
            slot_id__in=future_slot_ids,
        ).values_list("slot_id", flat=True)
    )

    for slot in future_slots:
        # Booking.slot uses PROTECT, including old/cancelled bookings, so any
        # referenced slot must remain exactly as in the original serializer.
        if slot.id in booked_slot_ids:
            continue

        if (slot.start, slot.end) not in desired_set:
            slot.delete()

    existing_set = set(
        AvailabilitySlot.objects.filter(
            room=room,
        ).values_list(
            "start",
            "end",
        )
    )

    new_slots = [
        AvailabilitySlot(
            room=room,
            start=slot_start,
            end=slot_end,
            max_bookings=1,
        )
        for slot_start, slot_end in desired_slots
        if (slot_start, slot_end) not in existing_set
    ]

    AvailabilitySlot.objects.bulk_create(
        new_slots,
        ignore_conflicts=True,
    )


def install_room_availability_slot_query_optimization():
    """Install the bounded-query availability-slot synchronizer."""
    global _INSTALLED

    if _INSTALLED:
        return

    RoomSerializer._sync_availability_slots = _optimized_sync_availability_slots
    _INSTALLED = True
