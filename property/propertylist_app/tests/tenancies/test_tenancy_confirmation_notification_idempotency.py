from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_send_tenancy_notification

pytestmark = pytest.mark.django_db


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

    # This regression is about persisted bell notifications. External delivery
    # side effects are irrelevant and must not make the retry assertion flaky.
    monkeypatch.setattr(
        "propertylist_app.tasks.push_user_realtime_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "propertylist_app.tasks.queue_notification_email",
        lambda *args, **kwargs: None,
        raising=False,
    )

    first_result = task_send_tenancy_notification(
        tenancy.id,
        "confirmed",
    )
    second_result = task_send_tenancy_notification(
        tenancy.id,
        "confirmed",
    )

    assert first_result == 2
    assert second_result == 2

    notifications = Notification.objects.filter(
        type="tenancy_confirmed",
        target_type="tenancy",
        target_id=tenancy.id,
    )

    # Celery may retry the same task. Each party must still have exactly one
    # persisted confirmation notification for this tenancy.
    assert notifications.count() == 2
    assert notifications.filter(user=landlord).count() == 1
    assert notifications.filter(user=tenant).count() == 1
