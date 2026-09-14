from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.api.views.common import _listing_state_for_room
from propertylist_app.listing_expiry_tasks import (
    listing_expiry_sweep,
    listing_expiry_warning_sweep,
)
from propertylist_app.models import Payment, Room


pytestmark = pytest.mark.django_db


def _seed_listing_expiry_templates():
    NotificationTemplate.objects.create(
        key="listing.expiring",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Your RentCrib listing is expiring soon",
        body="Hi {{ user.first_name }} - {{ room.title }} expires {{ room.paid_until }}",
        is_active=True,
    )
    NotificationTemplate.objects.create(
        key="listing.expired",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Your RentCrib listing has expired",
        body="Hi {{ user.first_name }} - {{ room.title }} has expired",
        is_active=True,
    )


def _paid_active_room(*, user_factory, room_factory, username):
    owner = user_factory(username=username, email=f"{username}@example.com")
    room = room_factory(property_owner=owner)
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = True
    room.paid_until = date.today() + timedelta(days=30)
    room.save(update_fields=["status", "is_available", "paid_until", "updated_at"])

    payment = Payment.objects.create(
        user=owner,
        room=room,
        provider=Payment.Provider.STRIPE,
        amount=Decimal("5.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    return owner, room, payment


def _age_payment(payment, minutes):
    aged_at = timezone.now() - timedelta(minutes=minutes)
    Payment.objects.filter(pk=payment.pk).update(updated_at=aged_at)
    payment.refresh_from_db()
    return aged_at


def test_qa_warns_five_minutes_before_twenty_minute_ad_expiry_once(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "true")
    _seed_listing_expiry_templates()
    owner, room, payment = _paid_active_room(
        user_factory=user_factory,
        room_factory=room_factory,
        username="qa_expiry_warning_owner",
    )

    _age_payment(payment, 14)
    assert listing_expiry_warning_sweep() == 0
    assert not OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.expiring",
    ).exists()

    _age_payment(payment, 15.5)
    assert listing_expiry_warning_sweep() == 1
    assert listing_expiry_warning_sweep() == 0

    warning = OutboundNotification.objects.get(
        user=owner,
        template_key="listing.expiring",
    )
    assert warning.context["room_id"] == room.id
    assert warning.context["room"]["paid_until"] == "in about 5 minutes (QA test)"


def test_qa_twenty_minutes_moves_listing_only_to_ads_expired_and_queues_expired_email(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "true")
    _seed_listing_expiry_templates()
    owner, room, payment = _paid_active_room(
        user_factory=user_factory,
        room_factory=room_factory,
        username="qa_ads_expired_owner",
    )

    _age_payment(payment, 20.5)
    assert listing_expiry_sweep() == 1

    room.refresh_from_db()
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until == date.today() - timedelta(days=1)
    assert _listing_state_for_room(room) == "expired"

    assert OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.expired",
        context__room_id=room.id,
    ).count() == 1

    # The expired payment entitlement must keep the room out of the public list.
    response = APIClient().get(reverse("api:room-list"))
    assert response.status_code == 200
    payload = response.data
    public_rooms = payload.get("results") or payload.get("data") or []
    if isinstance(public_rooms, dict):
        public_rooms = public_rooms.get("results", [])
    assert room.id not in {item["id"] for item in public_rooms}

    # Re-running the QA sweep must not duplicate the expiry transition/email.
    assert listing_expiry_sweep() == 0
    assert OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.expired",
        context__room_id=room.id,
    ).count() == 1


def test_fresh_renewal_payment_restarts_qa_twenty_minute_clock(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "true")
    _seed_listing_expiry_templates()
    owner, room, old_payment = _paid_active_room(
        user_factory=user_factory,
        room_factory=room_factory,
        username="qa_renewal_resets_clock_owner",
    )
    _age_payment(old_payment, 21)

    # A successful manual renewal/relist creates the new advertising cycle.
    new_payment = Payment.objects.create(
        user=owner,
        room=room,
        provider=Payment.Provider.STRIPE,
        amount=Decimal("5.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    room.paid_until = date.today() + timedelta(days=60)
    room.save(update_fields=["paid_until", "updated_at"])

    assert new_payment.updated_at > old_payment.updated_at
    assert listing_expiry_sweep() == 0

    room.refresh_from_db()
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until >= date.today()
    assert _listing_state_for_room(room) == "active"
    assert not OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.expired",
        context__room_id=room.id,
    ).exists()


def test_production_expiry_is_ads_expired_not_manual_hidden(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "false")
    _seed_listing_expiry_templates()
    owner, room, _payment = _paid_active_room(
        user_factory=user_factory,
        room_factory=room_factory,
        username="production_ads_expired_owner",
    )
    room.paid_until = date.today() - timedelta(days=1)
    room.save(update_fields=["paid_until", "updated_at"])

    assert listing_expiry_sweep() == 1
    room.refresh_from_db()

    # Natural expiry is represented by the expired entitlement, not hidden.
    assert room.status == Room.Lifecycle.ACTIVE
    assert _listing_state_for_room(room) == "expired"
    assert OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.expired",
        context__room_id=room.id,
    ).count() == 1
