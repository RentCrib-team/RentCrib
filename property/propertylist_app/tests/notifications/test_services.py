import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model
from notifications.models import NotificationTemplate, NotificationPreference, OutboundNotification, DeliveryAttempt
from notifications.services import NotificationService

pytestmark = pytest.mark.django_db

def setup_user(email="u@example.com", username="u1"):
    User = get_user_model()
    return User.objects.create_user(username=username, email=email, password="x")

def test_render_and_queue_and_deliver_email_success():
    u = setup_user()
    tpl = NotificationTemplate.objects.create(
        key="welcome",
        channel="email",
        subject="Hello {{ user.first_name }}",
        body="Hi {{ user.first_name }}!",
        is_active=True,
    )
    n = NotificationService.queue(user=u, template_key="welcome", context={"user": {"first_name": "Ada"}})
    assert isinstance(n, OutboundNotification)

    with patch("notifications.services.send_mail", return_value=1) as sm:
        NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_SENT
    assert DeliveryAttempt.objects.filter(notification=n, success=True).exists()
    sm.assert_called_once()

def test_deliver_skips_when_email_pref_disabled():
    u = setup_user()
    NotificationPreference.objects.create(user=u, email_enabled=False)
    NotificationTemplate.objects.create(
        key="any",
        channel="email",
        subject="S",
        body="B",
        is_active=True,
    )
    n = NotificationService.queue(user=u, template_key="any", context={})
    with patch("notifications.services.send_mail", return_value=1) as sm:
        NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_SKIPPED
    assert not DeliveryAttempt.objects.filter(notification=n).exists()
    sm.assert_not_called()

def test_deliver_fails_when_template_missing():
    u = setup_user()
    n = NotificationService.queue(user=u, template_key="missing.key", context={})
    NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_FAILED
    assert "Template not found" in (n.error or "")
    
    
    
@pytest.mark.django_db
def test_deliver_same_notification_twice_sends_email_only_once():
    from unittest.mock import patch
    from django.contrib.auth import get_user_model
    from notifications.models import (
        DeliveryAttempt,
        NotificationTemplate,
        OutboundNotification,
    )
    from notifications.services import NotificationService

    User = get_user_model()

    user = User.objects.create_user(
        username="duplicate_delivery_user",
        email="duplicate_delivery@example.com",
        password="pass12345",
    )

    NotificationTemplate.objects.create(
        key="test.duplicate_delivery",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Test email",
        body="Test body",
        is_active=True,
    )

    notification = OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="test.duplicate_delivery",
        context={},
    )

    with patch(
        "notifications.services.EmailTransport.send",
        return_value={"sent": 1},
    ) as mocked_send:
        NotificationService.deliver(notification)
        NotificationService.deliver(notification)

    notification.refresh_from_db()

    assert notification.status == OutboundNotification.STATUS_SENT

    assert mocked_send.call_count == 1

    assert DeliveryAttempt.objects.filter(
        notification=notification,
        success=True,
    ).count() == 1    
