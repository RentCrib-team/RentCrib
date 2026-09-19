from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.listing_expiry_tasks import listing_expiry_sweep
from propertylist_app.models import (
    Notification,
    Payment,
    Room,
    RoomListingBenefit,
    Tenancy,
)
from propertylist_app.services.listing_entitlements import (
    consume_complimentary_listing_benefit,
    grant_complimentary_listing_benefit,
    listing_fee_gbp,
)


pytestmark = pytest.mark.django_db


def _seed_complimentary_template():
    NotificationTemplate.objects.update_or_create(
        key="listing.complimentary_renewed",
        defaults={
            "channel": NotificationTemplate.CHANNEL_EMAIL,
            "subject": "Renewed free",
            "body": "Hi {{ user.first_name }} - {{ room.title }} - {{ cta_url }}",
            "is_active": True,
        },
    )


def _grant(owner, room):
    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("7.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    benefit, created = grant_complimentary_listing_benefit(payment)
    assert created is True
    return payment, benefit


def test_listing_fee_backend_source_of_truth_is_799():
    assert listing_fee_gbp() == Decimal("7.99")


def test_only_first_successful_payment_grants_one_complimentary_benefit(
    user_factory,
    room_factory,
):
    owner = user_factory(username="benefit_first_payment")
    room = room_factory(property_owner=owner)

    first = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("7.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    benefit, created = grant_complimentary_listing_benefit(first)

    assert created is True
    assert benefit.room_id == room.id
    assert benefit.consumed_at is None

    second = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("7.99"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    same_benefit, created_again = grant_complimentary_listing_benefit(second)

    assert created_again is False
    assert same_benefit.id == benefit.id
    assert RoomListingBenefit.objects.filter(room=room).count() == 1


def test_legacy_one_pound_payment_is_grandfathered_as_first_qualifying_payment(
    user_factory,
    room_factory,
):
    owner = user_factory(username="legacy_one_pound_benefit")
    room = room_factory(property_owner=owner)

    legacy_payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("1.00"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )
    current_payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=listing_fee_gbp(),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )

    benefit, created = grant_complimentary_listing_benefit(current_payment)

    assert created is True
    assert benefit.room_id == room.id
    assert benefit.granted_from_payment_id == legacy_payment.id
    assert benefit.consumed_at is None

    same_benefit, created_again = grant_complimentary_listing_benefit(current_payment)
    assert created_again is False
    assert same_benefit.id == benefit.id
    assert RoomListingBenefit.objects.filter(room=room).count() == 1


def test_paid_expiry_auto_consumes_available_benefit_and_renews_30_days(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "false")
    _seed_complimentary_template()

    owner = user_factory(
        username="benefit_auto_renew",
        email="benefit-auto@example.com",
    )
    room = room_factory(property_owner=owner)
    original_paid_until = timezone.localdate() - timedelta(days=1)

    room.status = Room.Lifecycle.ACTIVE
    room.is_available = True
    room.paid_until = original_paid_until
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    _, benefit = _grant(owner, room)

    assert listing_expiry_sweep() == 1

    room.refresh_from_db()
    benefit.refresh_from_db()

    assert room.paid_until == original_paid_until + timedelta(days=30)
    assert benefit.consumed_reason == (
        RoomListingBenefit.ConsumptionReason.AUTOMATIC_EXTENSION
    )
    assert benefit.complimentary_period_end == room.paid_until

    bell = Notification.objects.get(
        user=owner,
        type="listing_complimentary_renewed",
        target_type="room",
        target_id=room.id,
    )
    assert "automatically renewed" in bell.body

    email = OutboundNotification.objects.get(
        user=owner,
        template_key="listing.complimentary_renewed",
    )
    assert email.context["benefit_id"] == benefit.id
    assert f"tab=active&room={room.id}" in email.context["cta_url"]

    assert listing_expiry_sweep() == 0
    assert Notification.objects.filter(
        user=owner,
        type="listing_complimentary_renewed",
        target_id=room.id,
    ).count() == 1
    assert OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.complimentary_renewed",
    ).count() == 1


def test_rented_or_unavailable_room_preserves_benefit_for_future_relist(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "false")

    owner = user_factory(username="benefit_reserved_relist")
    room = room_factory(property_owner=owner)
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = False
    room.paid_until = timezone.localdate() - timedelta(days=1)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    _, benefit = _grant(owner, room)

    assert listing_expiry_sweep() == 0
    benefit.refresh_from_db()
    assert benefit.consumed_at is None

    room.is_available = True
    room.save(update_fields=["is_available", "updated_at"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["data"]["listing_state"] == "active"

    room.refresh_from_db()
    benefit.refresh_from_db()

    assert room.status == Room.Lifecycle.ACTIVE
    assert room.is_available is True
    assert room.paid_until == timezone.localdate() + timedelta(days=30)
    assert benefit.consumed_reason == (
        RoomListingBenefit.ConsumptionReason.FUTURE_RELIST
    )


def test_hidden_listing_does_not_burn_reserved_benefit_at_expiry(
    monkeypatch,
    user_factory,
    room_factory,
):
    monkeypatch.setenv("LISTING_EXPIRY_QA_MODE", "false")

    owner = user_factory(username="benefit_hidden")
    room = room_factory(property_owner=owner)
    room.status = Room.Lifecycle.HIDDEN
    room.is_available = True
    room.paid_until = timezone.localdate() - timedelta(days=1)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    _, benefit = _grant(owner, room)

    assert listing_expiry_sweep() == 0

    benefit.refresh_from_db()
    assert benefit.consumed_at is None


def test_after_complimentary_period_is_used_next_expired_relist_requires_payment(
    user_factory,
    room_factory,
):
    owner = user_factory(username="benefit_used_once")
    room = room_factory(property_owner=owner)
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = True
    room.paid_until = timezone.localdate() - timedelta(days=1)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    _, benefit = _grant(owner, room)

    activated = consume_complimentary_listing_benefit(
        room,
        reason=RoomListingBenefit.ConsumptionReason.FUTURE_RELIST,
    )
    assert activated is not None

    room.refresh_from_db()
    benefit.refresh_from_db()
    assert benefit.consumed_at is not None

    room.paid_until = timezone.localdate() - timedelta(days=1)
    room.save(update_fields=["paid_until", "updated_at"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert response.status_code == 400
    assert str(response.data["details"]["payment_required"]) == "True"


def test_benefit_survives_tenancy_end_and_is_used_on_later_relist(
    user_factory,
    room_factory,
):
    owner = user_factory(username="benefit_after_tenancy_owner")
    tenant = user_factory(username="benefit_after_tenancy_tenant")
    room = room_factory(property_owner=owner)

    # The landlord rents the room before the original paid advert expires.
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = False
    room.paid_until = timezone.localdate() + timedelta(days=15)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    _, benefit = _grant(owner, room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=owner,
        tenant=tenant,
        proposed_by=owner,
        move_in_date=timezone.localdate(),
        duration_months=1,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=timezone.now(),
        tenant_confirmed_at=timezone.now(),
    )

    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status", "updated_at"])

    room.refresh_from_db()
    benefit.refresh_from_db()

    # Ending the tenancy retires the old paid advert entitlement, but the
    # unused complimentary period stays reserved for this same room.
    assert room.is_available is True
    assert room.paid_until == timezone.localdate() - timedelta(days=1)
    assert benefit.consumed_at is None

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data

    room.refresh_from_db()
    benefit.refresh_from_db()

    assert room.paid_until == timezone.localdate() + timedelta(days=30)
    assert benefit.consumed_reason == (
        RoomListingBenefit.ConsumptionReason.FUTURE_RELIST
    )


def test_my_rooms_exposes_unused_complimentary_relist_benefit(
    user_factory,
    room_factory,
):
    owner = user_factory(username="benefit_my_rooms_owner")
    room = room_factory(property_owner=owner)
    _, benefit = _grant(owner, room)

    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.get(reverse("api:rooms-mine"))

    assert response.status_code == 200, response.data
    listing = next(
        item for item in response.data["results"] if item["id"] == room.id
    )
    assert listing["complimentary_relist_available"] is True

    benefit.consumed_at = timezone.now()
    benefit.consumed_reason = (
        RoomListingBenefit.ConsumptionReason.FUTURE_RELIST
    )
    benefit.save(
        update_fields=["consumed_at", "consumed_reason", "updated_at"]
    )

    response = client.get(reverse("api:rooms-mine"))

    assert response.status_code == 200, response.data
    listing = next(
        item for item in response.data["results"] if item["id"] == room.id
    )
    assert listing["complimentary_relist_available"] is False
