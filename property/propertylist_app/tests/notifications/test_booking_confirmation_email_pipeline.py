from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking, Room, RoomCategorie
from propertylist_app.notifications.tasks import send_due_notifications


pytestmark = pytest.mark.django_db


def test_booking_confirmation_email_pipeline_works_without_manual_template_seed():
    User = get_user_model()

    owner = User.objects.create_user(
        username="booking-owner",
        email="owner@example.com",
        password="x",
        first_name="Owner",
    )
    booker = User.objects.create_user(
        username="booking-seeker",
        email="seeker@example.com",
        password="x",
        first_name="Seeker",
    )

    template = NotificationTemplate.objects.get(
        key="booking.confirmation",
        channel=NotificationTemplate.CHANNEL_EMAIL,
    )
    assert template.is_active is True

    category = RoomCategorie.objects.create(
        name="Booking email regression",
        key="booking-email-regression",
        slug="booking-email-regression",
        active=True,
    )
    room = Room.objects.create(
        title="Email confirmation room",
        description="Regression test room",
        price_per_month=500,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    start = timezone.now() + timedelta(days=1)
    booking = Booking.objects.create(
        user=booker,
        room=room,
        start=start,
        end=start + timedelta(hours=1),
    )

    outbound = OutboundNotification.objects.get(
        user=booker,
        template_key="booking.confirmation",
    )
    assert outbound.status == OutboundNotification.STATUS_QUEUED
    assert outbound.context.get("booking_id") == booking.id

    with patch("notifications.services.send_mail", return_value=1) as send_mail:
        result = send_due_notifications()

    outbound.refresh_from_db()

    assert result["sent"] >= 1
    assert outbound.status == OutboundNotification.STATUS_SENT
    assert outbound.sent_at is not None

    booking_call = next(
        call
        for call in send_mail.call_args_list
        if call.kwargs.get("recipient_list") == [booker.email]
        and "viewing request" in call.kwargs.get("subject", "").lower()
    )
    assert booking_call.kwargs["recipient_list"] == [booker.email]
