from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_review_window_transition_releases_ended_tenancy_room_for_reletting(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="ended_room_release_landlord")
    tenant = user_factory(username="ended_room_release_tenant")
    room = room_factory(property_owner=landlord)
    now = timezone.now()

    # The room is unavailable while the tenancy is still running.
    room.is_available = False
    room.paid_until = date.today() + timedelta(days=28)
    room.relisted_at = now - timedelta(days=1)
    room.save(
        update_fields=[
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=12,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(minutes=30),
        tenant_confirmed_at=now - timedelta(minutes=30),
        review_open_at=now - timedelta(minutes=1),
        review_deadline_at=now + timedelta(minutes=9),
        still_living_confirmed_at=None,
    )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_ENDED
    assert room.is_available is True
    assert room.paid_until < date.today()
    assert room.relisted_at is None

    client = APIClient()
    client.force_authenticate(user=landlord)
    response = client.post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert response.status_code == 400
    assert str(response.data["details"]["payment_required"]) == "True"


def test_ended_tenancy_with_null_paid_until_is_not_public_and_requires_fresh_payment(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="ended_null_payment_landlord")
    tenant = user_factory(username="ended_null_payment_tenant")
    room = room_factory(property_owner=landlord)
    now = timezone.now()

    # Legacy/QA fixtures can reach a tenancy with no advert entitlement date.
    # While occupied, the room is unavailable; ending the tenancy must turn
    # that ambiguous NULL payment state into an explicitly expired one.
    room.status = "active"
    room.is_available = False
    room.paid_until = None
    room.relisted_at = now - timedelta(days=1)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=12,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(minutes=30),
        tenant_confirmed_at=now - timedelta(minutes=30),
    )

    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status", "updated_at"])

    room.refresh_from_db()

    assert room.is_available is True
    assert room.paid_until == date.today() - timedelta(days=1)
    assert room.relisted_at is None

    public_client = APIClient()
    public_response = public_client.get(reverse("api:room-list"))
    assert public_response.status_code == 200

    payload = public_response.data
    public_rooms = payload.get("results") or payload.get("data") or []
    if isinstance(public_rooms, dict):
        public_rooms = public_rooms.get("results", [])
    assert room.id not in {entry["id"] for entry in public_rooms}

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)
    publish_response = landlord_client.post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert publish_response.status_code == 400
    assert str(publish_response.data["details"]["payment_required"]) == "True"
