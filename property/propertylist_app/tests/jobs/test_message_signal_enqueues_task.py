import pytest
from django.contrib.auth import get_user_model

from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
)
from propertylist_app.models import (
    Message,
    MessageThread,
    Notification,
)

User = get_user_model()


@pytest.mark.django_db
def test_message_post_save_signal_creates_notifications():
    NotificationTemplate.objects.create(
        key="message.new",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="New message",
        body="You have a new message.",
        is_active=True,
    )

    sender = User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="x",
    )
    recipient = User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="x",
    )

    thread = MessageThread.objects.create()
    thread.participants.set([sender, recipient])

    message = Message.objects.create(
        thread=thread,
        sender=sender,
        body="Hi!",
    )

    in_app_notification = Notification.objects.get(
        user=recipient,
        type=Notification.Type.MESSAGE,
        thread=thread,
        message=message,
    )

    assert in_app_notification.title == "New message"
    assert in_app_notification.body == "Hi!"

    outbound_notification = OutboundNotification.objects.get(
        user=recipient,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="message.new",
    )

    assert outbound_notification.status == OutboundNotification.STATUS_QUEUED
    assert outbound_notification.context["thread_id"] == thread.id
    assert outbound_notification.context["message_id"] == message.id
    assert outbound_notification.context["sender"]["name"] == "alice"
    assert outbound_notification.context["snippet"] == "Hi!"

    assert not Notification.objects.filter(
        user=sender,
        type=Notification.Type.MESSAGE,
        message=message,
    ).exists()

    assert not OutboundNotification.objects.filter(
        user=sender,
        template_key="message.new",
    ).exists()