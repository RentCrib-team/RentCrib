import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Message, MessageRead, MessageThread


@pytest.mark.django_db
def test_thread_read_endpoint_can_toggle_read_back_to_unread():
    sender = User.objects.create_user(
        username="unread_sender",
        email="unread-sender@example.com",
        password="pass12345",
    )
    recipient = User.objects.create_user(
        username="unread_recipient",
        email="unread-recipient@example.com",
        password="pass12345",
    )

    thread = MessageThread.objects.create()
    thread.participants.set([sender, recipient])

    inbound = Message.objects.create(
        thread=thread,
        sender=sender,
        body="Normal inbound message",
    )
    system_message = Message.objects.create(
        thread=thread,
        sender=recipient,
        body="System workflow message",
        metadata={"system_event": True},
    )
    outbound = Message.objects.create(
        thread=thread,
        sender=recipient,
        body="Recipient's own message",
    )

    client = APIClient()
    client.force_authenticate(user=recipient)

    url = reverse(
        "v1:thread-mark-read",
        kwargs={"thread_id": thread.id},
    )

    mark_read = client.post(url, {}, format="json")
    assert mark_read.status_code == 200

    assert set(
        MessageRead.objects.filter(
            user=recipient,
            message__thread=thread,
        ).values_list("message_id", flat=True)
    ) == {inbound.id, system_message.id}

    mark_unread = client.post(
        url,
        {"is_read": False},
        format="json",
    )
    assert mark_unread.status_code == 200

    assert not MessageRead.objects.filter(
        user=recipient,
        message_id__in=[inbound.id, system_message.id],
    ).exists()
    assert not MessageRead.objects.filter(
        user=recipient,
        message=outbound,
    ).exists()

    assert mark_unread.data["data"]["marked"] == 2
    assert mark_unread.data["data"]["thread_unread_count"] == 2
    assert mark_unread.data["data"]["account_unread_total"] == 2

    mark_read_again = client.post(
        url,
        {"is_read": True},
        format="json",
    )
    assert mark_read_again.status_code == 200
    assert mark_read_again.data["data"]["thread_unread_count"] == 0
    assert MessageRead.objects.filter(
        user=recipient,
        message_id__in=[inbound.id, system_message.id],
    ).count() == 2
