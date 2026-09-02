import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync

from propertylist_app.consumers import RealtimeConsumer
from propertylist_app.services.realtime import (
    push_user_realtime_event,
)


@pytest.mark.django_db(transaction=True)
def test_realtime_event_contains_safe_performance_metadata():
    layer = AsyncMock()

    data = {
        "thread_id": 72,
        "message_id": 999999,
        "sender_id": 20,
        "body": "must not enter performance metadata",
        "token": "must-not-enter-performance-metadata",
    }

    with patch(
        "propertylist_app.services.realtime.get_channel_layer",
        return_value=layer,
    ):
        push_user_realtime_event(
            43,
            "new_message",
            data,
        )

    layer.group_send.assert_awaited_once()

    group_name, event = layer.group_send.await_args.args

    assert group_name == "user_43"
    assert event["type"] == "realtime_event"
    assert event["event_type"] == "new_message"
    assert event["data"] == data

    performance = event["performance"]

    assert performance["event_id"]
    assert performance["correlation_id"]
    assert (
        performance["event_id"]
        == performance["correlation_id"]
    )

    datetime.fromisoformat(
        performance["event_created_at"]
    )
    datetime.fromisoformat(
        performance["group_send_started_at"]
    )

    assert "body" not in performance
    assert "token" not in performance
    assert "credentials" not in performance
    assert "authorization" not in performance


def test_realtime_consumer_forwards_performance_metadata():
    consumer = RealtimeConsumer()
    consumer.send = AsyncMock()

    event = {
        "type": "realtime_event",
        "event_type": "new_message",
        "data": {
            "thread_id": 72,
            "message_id": 999999,
        },
        "performance": {
            "event_id": "event-123",
            "correlation_id": "event-123",
            "event_created_at": (
                "2026-08-31T08:00:00+00:00"
            ),
            "group_send_started_at": (
                "2026-08-31T08:00:00.010000+00:00"
            ),
        },
    }

    async_to_sync(consumer.realtime_event)(event)

    consumer.send.assert_awaited_once()

    sent_text = consumer.send.await_args.kwargs[
        "text_data"
    ]
    payload = json.loads(sent_text)

    assert payload["type"] == "new_message"

    assert payload["data"] == {
        "thread_id": 72,
        "message_id": 999999,
    }

    assert payload["performance"] == event["performance"]