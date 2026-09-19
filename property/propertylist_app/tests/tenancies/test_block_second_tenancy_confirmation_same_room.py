from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking, Message, Notification, Tenancy
from propertylist_app.tasks import task_send_tenancy_notification

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


def _tenant_claim(*, client, room, landlord, offset_days):
    response = client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=offset_days)),
            "duration_months": 6,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return Tenancy.objects.get(id=response.data.get("data", response.data)["id"])


def test_confirming_one_tenant_claim_retires_competing_claims_for_room(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="exclusive_confirm_landlord")
    tenant_a = user_factory(username="exclusive_confirm_tenant_a")
    tenant_b = user_factory(username="exclusive_confirm_tenant_b")
    room = room_factory(property_owner=landlord)

    _completed_booking(tenant=tenant_a, room=room, minutes_ago=20)
    _completed_booking(tenant=tenant_b, room=room, minutes_ago=10)

    tenant_a_client = APIClient()
    tenant_a_client.force_authenticate(user=tenant_a)
    tenant_b_client = APIClient()
    tenant_b_client.force_authenticate(user=tenant_b)
    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)

    claim_a = _tenant_claim(
        client=tenant_a_client,
        room=room,
        landlord=landlord,
        offset_days=7,
    )
    claim_b = _tenant_claim(
        client=tenant_b_client,
        room=room,
        landlord=landlord,
        offset_days=14,
    )

    assert claim_a.status == Tenancy.STATUS_PROPOSED
    assert claim_b.status == Tenancy.STATUS_PROPOSED

    first_confirm = landlord_client.post(
        f"/api/v1/tenancies/{claim_a.id}/respond/",
        data={
            "action": "confirm",
            "move_in_date": str(claim_a.move_in_date),
            "duration_months": claim_a.duration_months,
        },
        format="json",
    )
    assert first_confirm.status_code == 200, first_confirm.data

    claim_a.refresh_from_db()
    claim_b.refresh_from_db()
    room.refresh_from_db()

    assert claim_a.status in {Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE}
    assert room.is_available is False

    # Once one tenancy owns the room, other still-proposed claims are stale.
    # They must be retired immediately so no old Agree/Edit/Not-my-tenant path
    # survives into a room that is already rented to somebody else.
    assert claim_b.status == Tenancy.STATUS_CANCELLED

    second_confirm = landlord_client.post(
        f"/api/v1/tenancies/{claim_b.id}/respond/",
        data={
            "action": "confirm",
            "move_in_date": str(claim_b.move_in_date),
            "duration_months": claim_b.duration_months,
        },
        format="json",
    )
    assert second_confirm.status_code == 400, second_confirm.data

    live = Tenancy.objects.filter(
        room=room,
        status__in=[Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE],
    )
    assert live.count() == 1
    assert live.get().id == claim_a.id

    assert not Tenancy.objects.filter(
        room=room,
        status=Tenancy.STATUS_PROPOSED,
    ).exists()


def test_room_secured_notice_replaces_stale_proposal_notification(
    user_factory,
    room_factory,
    monkeypatch,
):
    """A delayed proposal task must not revive a claim retired by another tenant."""

    landlord = user_factory(username="exclusive_notice_landlord")
    tenant_a = user_factory(username="exclusive_notice_tenant_a")
    tenant_b = user_factory(username="exclusive_notice_tenant_b")
    room = room_factory(property_owner=landlord)

    _completed_booking(tenant=tenant_a, room=room, minutes_ago=20)
    _completed_booking(tenant=tenant_b, room=room, minutes_ago=10)

    tenant_a_client = APIClient()
    tenant_a_client.force_authenticate(user=tenant_a)
    tenant_b_client = APIClient()
    tenant_b_client.force_authenticate(user=tenant_b)
    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)

    # Do not depend on a broker in this regression test; execute the queued
    # work in the exact order that previously exposed the race.
    monkeypatch.setattr(
        task_send_tenancy_notification,
        "delay",
        lambda *args, **kwargs: None,
    )

    claim_a = _tenant_claim(
        client=tenant_a_client,
        room=room,
        landlord=landlord,
        offset_days=7,
    )
    claim_b = _tenant_claim(
        client=tenant_b_client,
        room=room,
        landlord=landlord,
        offset_days=14,
    )

    response = landlord_client.post(
        f"/api/v1/tenancies/{claim_a.id}/respond/",
        data={"action": "confirm"},
        format="json",
    )
    assert response.status_code == 200, response.data

    claim_b.refresh_from_db()
    assert claim_b.status == Tenancy.STATUS_CANCELLED

    NotificationTemplate.objects.create(
        key="tenancy.cancelled",
        channel="email",
        subject="Tenancy update",
        body="{{ room_title }}",
        is_active=True,
    )

    # This simulates the old queued job running after the losing claim was
    # retired. It must create nothing.
    assert task_send_tenancy_notification(claim_b.id, "proposed") == 0
    assert not Notification.objects.filter(
        user=tenant_b,
        type="tenancy_proposed",
        target_id=claim_b.id,
    ).exists()

    assert task_send_tenancy_notification(claim_b.id, "room_secured") == 1
    assert task_send_tenancy_notification(claim_b.id, "room_secured") == 1

    notification = Notification.objects.get(
        user=tenant_b,
        type="tenancy_room_secured",
        target_type="tenancy",
        target_id=claim_b.id,
    )
    assert "another seeker" in notification.body.lower()
    assert "no further tenancy updates" in notification.body.lower()

    assert Message.objects.filter(
        metadata__tenancy_id=claim_b.id,
        metadata__event_type="room_secured",
    ).count() == 1
    assert OutboundNotification.objects.filter(
        user=tenant_b,
        template_key="tenancy.cancelled",
        context__room_secured_elsewhere=True,
    ).count() == 1
