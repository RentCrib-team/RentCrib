import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Room, RoomCategorie, Tenancy


pytestmark = pytest.mark.django_db
API_PREFIX = "/api/v1"


def _make_user(username):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner, suffix):
    category = RoomCategorie.objects.create(name=f"QA update timing {suffix}")
    return Room.objects.create(
        title=f"QA tenancy update timer {suffix}",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=category,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.parametrize("original_proposer", ["landlord", "tenant"])
def test_tenancy_update_schedules_still_living_reminder_ten_minutes_later(
    original_proposer,
):
    landlord = _make_user(f"update_timer_landlord_{original_proposer}")
    tenant = _make_user(f"update_timer_tenant_{original_proposer}")
    room = _make_room(landlord, original_proposer)

    now = timezone.now()
    Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2) + timedelta(minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    landlord_client = _client_for(landlord)
    tenant_client = _client_for(tenant)

    if original_proposer == "landlord":
        proposer_client = landlord_client
        reviewer_client = tenant_client
        counterparty_id = tenant.id
    else:
        proposer_client = tenant_client
        reviewer_client = landlord_client
        counterparty_id = landlord.id

    proposal_response = proposer_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": counterparty_id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert proposal_response.status_code == 201, proposal_response.data

    tenancy_id = proposal_response.data.get(
        "data",
        proposal_response.data,
    )["id"]

    before_update = timezone.now()

    update_response = reviewer_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )

    after_update = timezone.now()

    assert update_response.status_code == 200, update_response.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.status in {
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    }

    expected_earliest = before_update + timedelta(minutes=10)
    expected_latest = after_update + timedelta(minutes=10)

    assert (
        expected_earliest
        <= tenancy.still_living_check_at
        <= expected_latest
    )
