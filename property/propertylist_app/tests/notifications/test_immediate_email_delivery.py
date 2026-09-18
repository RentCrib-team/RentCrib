from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from notifications.models import (
    DeliveryAttempt,
    NotificationTemplate,
    OutboundNotification,
)
from notifications.tasks import deliver_outbound_notification


@override_settings(TESTING=False)
@pytest.mark.django_db(transaction=True)
def test_due_email_creation_dispatches_immediately_after_commit():
    user = get_user_model().objects.create_user(
        username="immediate_email_user",
        email="immediate@example.com",
        password="pass12345",
    )

    with patch(
        "notifications.tasks.deliver_outbound_notification.delay"
    ) as mocked_delay:
        notification = OutboundNotification.objects.create(
            user=user,
            channel=NotificationTemplate.CHANNEL_EMAIL,
            template_key="test.immediate",
            scheduled_for=timezone.now(),
        )

    mocked_delay.assert_called_once_with(notification.pk)


@override_settings(TESTING=False)
@pytest.mark.django_db(transaction=True)
def test_future_email_creation_does_not_dispatch_immediately():
    user = get_user_model().objects.create_user(
        username="future_email_user",
        email="future@example.com",
        password="pass12345",
    )

    with patch(
        "notifications.tasks.deliver_outbound_notification.delay"
    ) as mocked_delay:
        OutboundNotification.objects.create(
            user=user,
            channel=NotificationTemplate.CHANNEL_EMAIL,
            template_key="test.future",
            scheduled_for=timezone.now() + timedelta(minutes=5),
        )

    mocked_delay.assert_not_called()


@pytest.mark.django_db
def test_immediate_delivery_task_uses_existing_safe_delivery_pipeline():
    user = get_user_model().objects.create_user(
        username="delivery_task_user",
        email="delivery@example.com",
        password="pass12345",
    )
    NotificationTemplate.objects.create(
        key="test.delivery_task",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Immediate delivery",
        body="Test body",
        is_active=True,
    )
    notification = OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="test.delivery_task",
        scheduled_for=timezone.now(),
    )

    with patch(
        "notifications.services.EmailTransport.send",
        return_value={"sent": 1},
    ) as mocked_send:
        result = deliver_outbound_notification.run(notification.pk)

    notification.refresh_from_db()

    assert result == OutboundNotification.STATUS_SENT
    assert notification.status == OutboundNotification.STATUS_SENT
    assert mocked_send.call_count == 1
    assert DeliveryAttempt.objects.filter(
        notification=notification,
        success=True,
    ).count() == 1


@override_settings(TESTING=False)
@pytest.mark.django_db(transaction=True)
def test_immediate_enqueue_failure_leaves_email_for_periodic_fallback():
    user = get_user_model().objects.create_user(
        username="broker_failure_user",
        email="broker-failure@example.com",
        password="pass12345",
    )

    with patch(
        "notifications.tasks.deliver_outbound_notification.delay",
        side_effect=RuntimeError("broker unavailable"),
    ):
        notification = OutboundNotification.objects.create(
            user=user,
            channel=NotificationTemplate.CHANNEL_EMAIL,
            template_key="test.broker_failure",
            scheduled_for=timezone.now(),
        )

    notification.refresh_from_db()
    assert notification.status == OutboundNotification.STATUS_QUEUED
