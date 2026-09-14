from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep

pytestmark = pytest.mark.django_db


def test_unanswered_landlord_proposal_expires_and_releases_room_after_qa_window(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="proposal_expiry_landlord")
    tenant = user_factory(username="proposal_expiry_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
        end=now - timedelta(minutes=1),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    tenancy_id = response.data.get("data", response.data)["id"]
    tenancy = Tenancy.objects.get(id=tenancy_id)

    room.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_PROPOSED
    assert tenancy.proposed_by_id == landlord.id
    assert room.is_available is False

    # QA response window is 10 minutes. Simulate no tenant response.
    Tenancy.objects.filter(id=tenancy.id).update(
        created_at=timezone.now() - timedelta(minutes=11)
    )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert room.is_available is True
