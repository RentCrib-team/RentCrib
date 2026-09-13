from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking, Notification, Room, RoomCategorie, UserProfile


@pytest.mark.django_db
def test_booking_creation_signal_keeps_synchronous_database_work_bounded(django_user_model):
    landlord = django_user_model.objects.create_user(
        username="booking_perf_landlord",
        email="booking_perf_landlord@example.com",
    )
    seeker = django_user_model.objects.create_user(
        username="booking_perf_seeker",
        email="booking_perf_seeker@example.com",
    )

    UserProfile.objects.get_or_create(user=landlord)
    UserProfile.objects.get_or_create(user=seeker)

    category = RoomCategorie.objects.create(name="Booking performance", active=True)
    room = Room.objects.create(
        title="Booking performance room",
        category=category,
        property_owner=landlord,
        price_per_month=650,
        location="Southampton",
        property_type="flat",
    )

    NotificationTemplate.objects.create(
        key="booking.new",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
        subject="New booking",
        body="A viewing was booked.",
    )
    NotificationTemplate.objects.create(
        key="booking.confirmation",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
        subject="Booking confirmed",
        body="Your viewing is confirmed.",
    )

    start = timezone.now() + timedelta(days=2)

    with (
        patch(
            "propertylist_app.services.booking_creation_query_optimization."
            "push_user_realtime_event"
        ) as realtime_push,
        CaptureQueriesContext(connection) as queries,
    ):
        booking = Booking.objects.create(
            user=seeker,
            room=room,
            start=start,
            end=start + timedelta(hours=1),
            status=Booking.STATUS_ACTIVE,
        )

    assert len(queries) <= 12

    landlord_notification = Notification.objects.get(user=landlord, type="booking_created")
    assert landlord_notification.title == "New viewing booked"

    queued_templates = set(
        OutboundNotification.objects.filter(user__in=[landlord, seeker]).values_list(
            "template_key", flat=True
        )
    )
    assert queued_templates == {"booking.new", "booking.confirmation"}

    event_types = [call.args[1] for call in realtime_push.call_args_list]
    assert event_types == ["new_message", "new_message", "new_notification"]

    assert booking.room_id == room.id
    assert booking.user_id == seeker.id
