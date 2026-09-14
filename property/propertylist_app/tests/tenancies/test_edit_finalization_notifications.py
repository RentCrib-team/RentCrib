from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.api.views import tenancies as tenancy_views
from propertylist_app.models import Booking, Tenancy

pytestmark = pytest.mark.django_db


def test_one_time_edit_that_finalises_tenancy_queues_updated_and_confirmed_events(
    user_factory,
    room_factory,
    monkeypatch,
):
    landlord = user_factory(username="edit_notify_landlord")
    tenant = user_factory(username="edit_notify_tenant")
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

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)
    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    proposal = landlord_client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert proposal.status_code == 201, proposal.data
    tenancy_id = proposal.data.get("data", proposal.data)["id"]

    queued_events = []

    def fake_delay(queued_tenancy_id, event):
        queued_events.append((queued_tenancy_id, event))

    monkeypatch.setattr(
        tenancy_views.task_send_tenancy_notification,
        "delay",
        fake_delay,
    )

    response = tenant_client.post(
        f"/api/v1/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )
    assert response.status_code == 200, response.data

    tenancy = Tenancy.objects.get(id=tenancy_id)
    assert tenancy.status == Tenancy.STATUS_CONFIRMED
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None

    assert (tenancy.id, "updated") in queued_events
    assert (tenancy.id, "confirmed") in queued_events
