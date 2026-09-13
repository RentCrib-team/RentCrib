import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from unittest.mock import patch

from propertylist_app.models import (
    Message,
    MessageThread,
    Notification,
    UserProfile,
)


@pytest.mark.django_db
def test_human_message_signal_keeps_synchronous_database_work_bounded(
    django_user_model,
):
    sender = django_user_model.objects.create_user(
        username="message_perf_sender",
        email="message_perf_sender@example.com",
        password="testpass123",
    )
    recipient = django_user_model.objects.create_user(
        username="message_perf_recipient",
        email="message_perf_recipient@example.com",
        password="testpass123",
    )

    UserProfile.objects.get_or_create(user=sender)
    UserProfile.objects.get_or_create(user=recipient)

    thread = MessageThread.objects.create()
    thread.participants.set([sender, recipient])

    with (
        patch(
            "propertylist_app.services.message_creation_query_optimization."
            "push_user_realtime_event"
        ) as realtime_push,
        patch(
            "propertylist_app.services.message_creation_query_optimization."
            "_queue_email"
        ),
        CaptureQueriesContext(connection) as queries,
    ):
        message = Message.objects.create(
            thread=thread,
            sender=sender,
            body="Performance regression check",
            message_type=Message.TYPE_TEXT,
        )

    # One message INSERT plus fixed-cost recipient lookup, un-bin UPDATE,
    # one unread aggregate and notification creation. The old signal performed
    # separate deleted-state, thread-unread, bin-list and account-unread queries
    # and then fetched the same profile again for notification delivery.
    assert len(queries) <= 6

    notification = Notification.objects.get(
        user=recipient,
        type=Notification.Type.MESSAGE,
        thread=thread,
        message=message,
    )
    assert notification.title == "New message"

    event_types = [call.args[1] for call in realtime_push.call_args_list]
    assert event_types == [
        "new_message",
        "unread_count_changed",
        "new_notification",
    ]

    unread_payload = realtime_push.call_args_list[1].args[2]
    assert unread_payload == {
        "thread_id": thread.id,
        "thread_unread_count": 1,
        "account_unread_total": 1,
    }
