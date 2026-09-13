from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from notifications.models import NotificationTemplate, OutboundNotification
from notifications.services import NotificationService


pytestmark = pytest.mark.django_db


def test_transactional_email_uses_plain_text_fallback_and_html_alternative():
    user = get_user_model().objects.create_user(
        username="mime-recipient",
        email="recipient@example.com",
        password="x",
        first_name="Tenant",
    )

    NotificationTemplate.objects.create(
        key="test.mime",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Viewing update",
        body="<p>Hello <strong>{{ user.first_name }}</strong> &amp; welcome</p>",
        is_active=True,
    )

    notification = OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="test.mime",
        context={"user": {"first_name": "Tenant"}},
    )

    with patch(
        "notifications.services.EmailTransport.send",
        return_value={"sent": 1},
    ) as email_send:
        NotificationService.deliver(notification)

    email_send.assert_called_once()

    to_email, subject, plain_body = email_send.call_args.args
    html_body = email_send.call_args.kwargs["html_message"]

    assert to_email == user.email
    assert subject == "Viewing update"
    assert plain_body == "Hello Tenant & welcome"
    assert "<p>" not in plain_body
    assert "<strong>" not in plain_body
    assert html_body == "<p>Hello <strong>Tenant</strong> &amp; welcome</p>"
