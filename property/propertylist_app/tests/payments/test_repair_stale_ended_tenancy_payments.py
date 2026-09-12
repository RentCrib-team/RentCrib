from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from propertylist_app.models import Payment, Tenancy


pytestmark = pytest.mark.django_db


def _create_ended_tenancy(*, room, landlord, tenant):
    now = timezone.now()
    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=40),
        duration_months=1,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=40),
        tenant_confirmed_at=now - timedelta(days=40),
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )


def _create_succeeded_payment(*, room, user):
    return Payment.objects.create(
        user=user,
        room=room,
        provider=Payment.Provider.STRIPE,
        amount=Decimal("1.00"),
        currency="GBP",
        status=Payment.Status.SUCCEEDED,
    )


def test_repair_expires_only_entitlement_older_than_latest_ended_tenancy(
    user_factory,
    room_factory,
):
    now = timezone.now()
    today = timezone.localdate()
    landlord = user_factory(username="stale_entitlement_landlord")
    tenant = user_factory(username="stale_entitlement_tenant")

    stale_room = room_factory(property_owner=landlord)
    stale_room.paid_until = today + timedelta(days=23)
    stale_room.relisted_at = now
    stale_room.save(
        update_fields=[
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )
    stale_payment = _create_succeeded_payment(
        room=stale_room,
        user=landlord,
    )
    stale_tenancy = _create_ended_tenancy(
        room=stale_room,
        landlord=landlord,
        tenant=tenant,
    )
    Payment.objects.filter(pk=stale_payment.pk).update(
        created_at=now - timedelta(days=7),
    )
    Tenancy.objects.filter(pk=stale_tenancy.pk).update(
        updated_at=now - timedelta(days=3),
    )

    legitimately_repaid_room = room_factory(property_owner=landlord)
    legitimate_paid_until = today + timedelta(days=28)
    legitimate_relisted_at = now - timedelta(hours=1)
    legitimately_repaid_room.paid_until = legitimate_paid_until
    legitimately_repaid_room.relisted_at = legitimate_relisted_at
    legitimately_repaid_room.save(
        update_fields=[
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )
    legitimate_tenancy = _create_ended_tenancy(
        room=legitimately_repaid_room,
        landlord=landlord,
        tenant=tenant,
    )
    legitimate_payment = _create_succeeded_payment(
        room=legitimately_repaid_room,
        user=landlord,
    )
    Tenancy.objects.filter(pk=legitimate_tenancy.pk).update(
        updated_at=now - timedelta(days=7),
    )
    Payment.objects.filter(pk=legitimate_payment.pk).update(
        created_at=now - timedelta(days=3),
    )

    call_command("repair_stale_ended_tenancy_payments")

    stale_room.refresh_from_db()
    legitimately_repaid_room.refresh_from_db()

    assert stale_room.paid_until == today - timedelta(days=1)
    assert stale_room.relisted_at is None

    assert legitimately_repaid_room.paid_until == legitimate_paid_until
    assert legitimately_repaid_room.relisted_at == legitimate_relisted_at
