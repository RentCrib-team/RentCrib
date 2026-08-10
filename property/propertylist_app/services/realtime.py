import logging

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
    """

    def _send():
        try:
            channel_layer = get_channel_layer()

            if channel_layer is None:
                return

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                {
                    "type": "realtime_event",
                    "event_type": event_type,
                    "data": data,
                },
            )
        except Exception:
            logger.exception(
                "Realtime event delivery failed for user_id=%s event_type=%s",
                user_id,
                event_type,
            )

    transaction.on_commit(_send)