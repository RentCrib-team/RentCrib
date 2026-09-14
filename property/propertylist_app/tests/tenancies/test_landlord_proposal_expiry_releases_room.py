from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking, Tenancy
from propertylist_app.tasks import (
    task_send_tenancy_notification,
    task_tenancy_prompts_sweep,
)

pytestmark = pytest.mark.django_db


def test_unanswered_landlord_proposal_expires_releases_room_and_notifies_both(
    user_factory,
    room_factory,
    monkeypatch,
):
    Notification = apps.get_model("propertylist_app", "Notification")

    landlord = user_factory(username="proposal_expiry_landlord")
    tenant = user_factory(username="proposal_expiry_tenant")
    room = room_factory(property_owner=landlord)

    NotificationTemplate.objects.update_or_create(
        key="tenancy.cancelled",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        defaults={
            "subject": "Tenancy proposal expired",
            "body": "{{ room_title }} {{ cta_url }}",
            "is_active": True,
        },
    )

    # Execute the notification task synchronously so this regression proves
    # the persisted envelope/bell/email effects as well as state cleanup.
    monkeypatch.setattr(
        task_send_tenancy_notification,
        "delay",
        lambda tenancy_id, event: task_send_tenancy_notification(
            tenancy_id,
            event,
        ),
    )
    monkeypatch.setattr(
        "propertylist_app.tasks.push_user_realtime_event",
        lambda *args, **kwargs: None,
    )

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

    # One shared structured tenancy event is the envelope/inbox surface.
    messages = tenancy.room.message_threads.filter(
        messages__metadata__tenancy_id=tenancy.id,
        messages__metadata__event_type="cancelled",
    ).distinct()
    assert messages.exists()

    bells = Notification.objects.filter(
        type="tenancy_cancelled",
        target_type="tenancy",
        target_id=tenancy.id,
    )
    assert bells.count() == 2
    assert bells.filter(user=landlord).count() == 1
    assert bells.filter(user=tenant).count() == 1

    emails = OutboundNotification.objects.filter(
        template_key="tenancy.cancelled",
        context__tenancy_id=tenancy.id,
    )
    assert emails.count() == 2
    assert emails.filter(user=landlord).count() == 1
    assert emails.filter(user=tenant).count() == 1
