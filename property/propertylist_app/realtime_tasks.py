from celery import shared_task


@shared_task(
    name="propertylist_app.deliver_realtime_event",
    ignore_result=True,
)
def deliver_realtime_event(
    user_id: int,
    event_type: str,
    data: dict,
    event_id: str,
    correlation_id: str,
    event_created_at: str,
) -> None:
    """
    Deliver one realtime event outside the originating HTTP request.

    The caller registers this task with transaction.on_commit so events are
    never published for a transaction that later rolls back.
    """
    from propertylist_app.services.realtime import (
        deliver_user_realtime_event,
    )

    deliver_user_realtime_event(
        user_id=user_id,
        event_type=event_type,
        data=data,
        event_id=event_id,
        correlation_id=correlation_id,
        event_created_at=event_created_at,
    )
