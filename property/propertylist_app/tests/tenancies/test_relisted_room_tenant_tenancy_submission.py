from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _completed_booking(*, user, room, start):
    return Booking.objects.create(
        user=user,
        room=room,
        start=start,
        end=start + timedelta(minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _tenant_client(tenant):
    client = APIClient()
    client.force_authenticate(user=tenant)
    return client


def _proposal_payload(*, room, booking, landlord, days=7):
    return {
        "room_id": room.id,
        "booking_id": booking.id,
        "counterparty_user_id": landlord.id,
        "move_in_date": str(timezone.localdate() + timedelta(days=days)),
        "duration_months": 6,
    }


def test_fresh_viewing_ignores_historical_legacy_cancelled_tenant_claim(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="legacy_claim_landlord")
    tenant = user_factory(username="legacy_claim_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()

    historical_claim = Tenancy.objects.create(
        room=room,
        source_booking=None,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate() - timedelta(days=50),
        duration_months=1,
        status=Tenancy.STATUS_CANCELLED,
    )

    Tenancy.objects.filter(pk=historical_claim.pk).update(
        created_at=now - timedelta(days=40),
    )

    assert room.relisted_at is None
    assert historical_claim.source_booking_id is None

    fresh_booking = _completed_booking(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
    )

    response = _tenant_client(tenant).post(
        f"{API_PREFIX}/tenancies/propose/",
        data=_proposal_payload(
            room=room,
            booking=fresh_booking,
            landlord=landlord,
        ),
        format="json",
    )

    assert response.status_code == 201, response.data

    payload = response.data.get("data", response.data)
    tenancy = Tenancy.objects.get(pk=payload["id"])

    assert tenancy.source_booking_id == fresh_booking.id
    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.status == Tenancy.STATUS_PROPOSED


def test_cancelled_claim_for_same_source_booking_still_blocks_retry(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="same_booking_claim_landlord")
    tenant = user_factory(username="same_booking_claim_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    booking = _completed_booking(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
    )

    Tenancy.objects.create(
        room=room,
        source_booking=booking,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_CANCELLED,
    )

    response = _tenant_client(tenant).post(
        f"{API_PREFIX}/tenancies/propose/",
        data=_proposal_payload(
            room=room,
            booking=booking,
            landlord=landlord,
        ),
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "contact the landlord" in str(response.data).lower()
    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1


def test_current_viewing_legacy_null_source_claim_still_blocks_retry(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="legacy_current_claim_landlord")
    tenant = user_factory(username="legacy_current_claim_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    booking = _completed_booking(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
    )

    Tenancy.objects.create(
        room=room,
        source_booking=None,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_CANCELLED,
    )

    response = _tenant_client(tenant).post(
        f"{API_PREFIX}/tenancies/propose/",
        data=_proposal_payload(
            room=room,
            booking=booking,
            landlord=landlord,
            days=14,
        ),
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "contact the landlord" in str(response.data).lower()
    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1
