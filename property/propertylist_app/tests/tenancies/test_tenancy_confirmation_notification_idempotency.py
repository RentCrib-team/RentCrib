from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.tasks import task_send_tenancy_notification

pytestmark = pytest.mark.django_db


def _email_template(key, subject):
    return NotificationTemplate.objects.create(
        key=key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject=subject,
        body=subject,
        is_active=True,
    )


def test_confirmed_notification_task_is_idempotent_on_retry(
    user_factory,
    room_factory,
    monkeypatch,
):
    Notification = apps.get_model("propertylist_app", "Notification")
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="retry_confirm_landlord")
    tenant = user_factory(username="retry_confirm_tenant")
    room = room_factory(property_owner=landlord)

    _email_template("tenancy.confirmed", "Tenancy confirmed")

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=now,
        tenant_confirmed_at=now,
    )

    realtime_events = []
    monkeypatch.setattr(
        "propertylist_app.tasks.push_user_realtime_event",
        lambda *args, **kwargs: realtime_events.append((args, kwargs)),
    )

    first_result = task_send_tenancy_notification(tenancy.id, "confirmed")
    realtime_after_first_run = list(realtime_events)

    # Simulate a partial first execution: the landlord bell/realtime delivery
    # exists, but its queued email was lost before a retry.
    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key="tenancy.confirmed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
    )
    landlord_email.delete()

    second_result = task_send_tenancy_notification(tenancy.id, "confirmed")

    assert first_result == 2
    assert second_result == 2

    notifications = Notification.objects.filter(
        type="tenancy_confirmed",
        target_type="tenancy",
        target_id=tenancy.id,
    )

    assert notifications.count() == 2
    assert notifications.filter(user=landlord).count() == 1
    assert notifications.filter(user=tenant).count() == 1

    outbound = OutboundNotification.objects.filter(
        template_key="tenancy.confirmed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
    )

    # Retry repairs the missing landlord email without duplicating the tenant's.
    assert outbound.count() == 2
    assert outbound.filter(user=landlord).count() == 1
    assert outbound.filter(user=tenant).count() == 1

    # The retry must not replay bell/message/unread realtime events.
    assert realtime_events == realtime_after_first_run


def test_proposal_notification_task_does_not_duplicate_email_on_retry(
    user_factory,
    room_factory,
    monkeypatch,
):
    Notification = apps.get_model("propertylist_app", "Notification")
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="retry_proposal_landlord")
    tenant = user_factory(username="retry_proposal_tenant")
    room = room_factory(property_owner=landlord)

    _email_template("tenancy.proposed", "Review tenancy information")

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
        landlord_confirmed_at=timezone.now(),
    )

    monkeypatch.setattr(
        "propertylist_app.tasks.push_user_realtime_event",
        lambda *args, **kwargs: None,
    )

    first_result = task_send_tenancy_notification(tenancy.id, "proposed")
    second_result = task_send_tenancy_notification(tenancy.id, "proposed")

    assert first_result == 1
    assert second_result == 1

    # Proposal bell is already get_or_create based; keep proving that guarantee.
    notifications = Notification.objects.filter(
        user=tenant,
        type="tenancy_proposed",
        target_type="tenancy",
        target_id=tenancy.id,
    )
    assert notifications.count() == 1

    # The email side must be equally retry-safe.
    outbound = OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.proposed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
    )
    assert outbound.count() == 1
