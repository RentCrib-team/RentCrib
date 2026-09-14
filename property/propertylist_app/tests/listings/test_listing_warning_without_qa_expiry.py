from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.api.views.common import _listing_state_for_room
from propertylist_app.listing_expiry_tasks import (
    listing_expiry_sweep,
    listing_expiry_warning_sweep,
)
from propertylist_app.models import Payment, Room


pytestmark = pytest.mark.django_db


def test_qa_warning_does_not_shorten_thirty_day_listing_lifetime(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "true")

    owner = user_factory(
        username="qa_warning_only_owner",
        email="qa_warning_only_owner@example.com",
    )
    room = room_factory(property_owner=owner)
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = True
    room.paid_until = date.today() + timedelta(days=30)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    payment = Payment.objects.create(
        user=owner,
        room=room,
        provider=Payment.Provider.STRIPE,
        amount=Decimal("5.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )

    NotificationTemplate.objects.create(
        key="listing.expiring",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Your RentCrib listing is expiring soon",
        body="Hi {{ user.first_name }} - {{ room.title }} expires {{ room.paid_until }}",
        is_active=True,
    )

    Payment.objects.filter(pk=payment.pk).update(
        updated_at=timezone.now() - timedelta(minutes=20.5)
    )

    assert listing_expiry_warning_sweep() == 1
    assert listing_expiry_warning_sweep() == 0

    warning = OutboundNotification.objects.get(
        user=owner,
        template_key="listing.expiring",
    )
    assert warning.context["room_id"] == room.id
    assert warning.context["room"]["paid_until"] == str(room.paid_until)

    assert listing_expiry_sweep() == 0

    room.refresh_from_db()
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.is_available is True
    assert room.paid_until == date.today() + timedelta(days=30)
    assert _listing_state_for_room(room) == "active"
