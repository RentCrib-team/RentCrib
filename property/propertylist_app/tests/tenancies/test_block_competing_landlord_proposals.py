from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Tenancy

pytestmark = pytest.mark.django_db


def _completed_booking(*, tenant, room, minutes_ago):
    now = timezone.now()
    Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=minutes_ago + 30),
        end=now - timedelta(minutes=minutes_ago),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def test_landlord_cannot_open_competing_live_proposals_for_same_room(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="competing_proposal_landlord")
    tenant_a = user_factory(username="competing_proposal_tenant_a")
    tenant_b = user_factory(username="competing_proposal_tenant_b")
    room = room_factory(property_owner=landlord)

    _completed_booking(tenant=tenant_a, room=room, minutes_ago=20)
    _completed_booking(tenant=tenant_b, room=room, minutes_ago=10)

    client = APIClient()
    client.force_authenticate(user=landlord)

    first = client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant_a.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert first.status_code == 201, first.data

    room.refresh_from_db()
    assert room.is_available is False

    second = client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant_b.id,
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 6,
        },
        format="json",
    )

    # A landlord-originated proposal takes the room off availability. Until it
    # is confirmed/cancelled/expired, the same landlord must not create another
    # competing live proposal for a different seeker on that same room.
    assert second.status_code == 400, second.data

    live = Tenancy.objects.filter(
        room=room,
        landlord=landlord,
        status__in=[
            Tenancy.STATUS_PROPOSED,
            Tenancy.STATUS_CONFIRMED,
            Tenancy.STATUS_ACTIVE,
        ],
        proposed_by=landlord,
    )
    assert live.count() == 1
    assert live.get().tenant_id == tenant_a.id
