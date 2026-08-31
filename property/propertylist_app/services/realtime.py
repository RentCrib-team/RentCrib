import logging
import time
import uuid
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


logger = logging.getLogger(__name__)


def push_user_realtime_event(
    user_id: int,
    event_type: str,
    data: dict,
) -> None:
    """
    Push one realtime event to a signed-in RentCrib user.

    Delivery happens only after the surrounding database transaction commits.
    A temporary Redis/WebSocket problem must never break the normal REST,
    notification, or email flow.

    Performance instrumentation contains only safe identifiers and timing
    metadata. Event payloads, message bodies, credentials, and tokens are
    never written to performance logs.
    """
    event_id = str(uuid.uuid4())
    correlation_id = event_id
    event_created_at = datetime.now(timezone.utc).isoformat()

    safe_ids = {
        key: data.get(key)
        for key in (
            "thread_id",
            "message_id",
            "notification_id",
        )
        if data.get(key) is not None
    }

    def _send():
        try:
            channel_layer = get_channel_layer()

            if channel_layer is None:
                logger.warning(
                    "Realtime performance event_id=%s correlation_id=%s "
                    "event_type=%s user_id=%s "
                    "stage=channel_layer_missing %s",
                    event_id,
                    correlation_id,
                    event_type,
                    user_id,
                    safe_ids,
                )
                return

            group_send_started_at = datetime.now(
                timezone.utc
            ).isoformat()

            group_send_started = time.perf_counter()

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                {
                    "type": "realtime_event",
                    "event_type": event_type,
                    "data": data,
                    "performance": {
                        "event_id": event_id,
                        "correlation_id": correlation_id,
                        "event_created_at": event_created_at,
                        "group_send_started_at": group_send_started_at,
                    },
                },
            )

            group_send_ms = (
                time.perf_counter() - group_send_started
            ) * 1000

            logger.info(
                "Realtime performance "
                "event_id=%s correlation_id=%s "
                "event_type=%s user_id=%s "
                "stage=group_send_complete "
                "group_send_ms=%.3f %s",
                event_id,
                correlation_id,
                event_type,
                user_id,
                group_send_ms,
                safe_ids,
            )

        except Exception:
            logger.exception(
                "Realtime event delivery failed "
                "event_id=%s correlation_id=%s "
                "user_id=%s event_type=%s %s",
                event_id,
                correlation_id,
                user_id,
                event_type,
                safe_ids,
            )

    transaction.on_commit(_send)