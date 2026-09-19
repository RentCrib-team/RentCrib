import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from unittest.mock import patch

from propertylist_app.models import (
    Message,
    MessageThread,
    Notification,
    UserProfile,
)
from propertylist_app.api.views.messaging import MessageListCreateView


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


@pytest.mark.django_db
def test_message_send_request_query_count_does_not_grow_with_account_history(
    django_user_model,
):
    # User primary keys are reused between database tests, while the locmem
    # throttle cache survives rollbacks. Start this rate-limit-independent
    # performance test with a clean cache.
    cache.clear()

    sender = django_user_model.objects.create_user(
        username="message_scale_sender",
        email="message_scale_sender@example.com",
        password="testpass123",
    )
    recipient = django_user_model.objects.create_user(
        username="message_scale_recipient",
        email="message_scale_recipient@example.com",
        password="testpass123",
    )
    history_peer = django_user_model.objects.create_user(
        username="message_scale_history_peer",
        email="message_scale_history_peer@example.com",
        password="testpass123",
    )

    UserProfile.objects.get_or_create(user=sender)
    UserProfile.objects.get_or_create(user=recipient)
    UserProfile.objects.get_or_create(user=history_peer)

    target_thread = MessageThread.objects.create()
    target_thread.participants.set([sender, recipient])

    client = APIClient()
    client.force_authenticate(user=sender)
    url = f"/api/v1/messages/threads/{target_thread.id}/messages/"

    with (
        patch.object(MessageListCreateView, "throttle_classes", []),
        patch(
            "propertylist_app.services.message_creation_query_optimization."
            "push_user_realtime_event"
        ) as realtime_push,
        patch(
            "propertylist_app.services.message_creation_query_optimization."
            "_queue_email"
        ),
    ):
        warmup_response = client.post(
            url,
            {"body": "Warmup send"},
            format="json",
        )
        assert warmup_response.status_code == 201

        realtime_push.reset_mock()

        with CaptureQueriesContext(connection) as baseline_queries:
            baseline_response = client.post(
                url,
                {"body": "Baseline send"},
                format="json",
            )

        assert baseline_response.status_code == 201

        historical_messages = []
        for thread_index in range(30):
            history_thread = MessageThread.objects.create()
            history_thread.participants.set([recipient, history_peer])

            for message_index in range(20):
                historical_messages.append(
                    Message(
                        thread=history_thread,
                        sender=history_peer,
                        body=(
                            f"Historical message {thread_index}-"
                            f"{message_index}"
                        ),
                        message_type=Message.TYPE_TEXT,
                    )
                )

        # Deliberately bypass post-save signals while constructing historical
        # account load. The measured operation below is the real send endpoint.
        Message.objects.bulk_create(historical_messages)

        realtime_push.reset_mock()

        with CaptureQueriesContext(connection) as loaded_queries:
            loaded_response = client.post(
                url,
                {"body": "Loaded account send"},
                format="json",
            )

    assert loaded_response.status_code == 201
    assert len(loaded_queries) <= len(baseline_queries)

    # Prove the loaded request really traversed the recipient's historical
    # unread state rather than accidentally measuring an empty-account path.
    loaded_unread_payload = realtime_push.call_args_list[1].args[2]
    assert loaded_unread_payload == {
        "thread_id": target_thread.id,
        "thread_unread_count": 3,
        "account_unread_total": len(historical_messages) + 3,
    }
