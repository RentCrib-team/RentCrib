from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking

pytestmark = pytest.mark.django_db


def test_repeating_same_reschedule_does_not_queue_duplicate_email(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="reschedule_email_landlord")
    seeker = user_factory(username="reschedule_email_seeker")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    booking = Booking.objects.create(
        user=seeker,
        room=room,
        start=now + timedelta(days=2),
        end=now + timedelta(days=2, minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    NotificationTemplate.objects.create(
        key="booking.updated",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Viewing updated",
        body="Your viewing was updated.",
        is_active=True,
    )

    new_start = now + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)
    payload = {
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }

    client = APIClient()
    client.force_authenticate(user=seeker)

    first = client.patch(
        f"/api/v1/bookings/{booking.id}/reschedule/",
        data=payload,
        format="json",
    )
    assert first.status_code == 200, first.data

    second = client.patch(
        f"/api/v1/bookings/{booking.id}/reschedule/",
        data=payload,
        format="json",
    )
    assert second.status_code == 200, second.data

    queued = OutboundNotification.objects.filter(
        user=landlord,
        template_key="booking.updated",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        context__booking_id=booking.id,
        context__new_start=new_start.isoformat(),
        context__new_end=new_end.isoformat(),
    )

    assert queued.count() == 1
