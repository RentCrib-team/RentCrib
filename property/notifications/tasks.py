"""
Bridge module so old task paths keep working.

Celery Beat uses:
- notifications.tasks.send_due_notifications
- notifications.tasks.notify_listing_expiring
"""

from celery import shared_task

from propertylist_app.notifications.tasks import (
    send_due_notifications,
    notify_listing_expiring,
)


@shared_task(name="notifications.tasks.deliver_outbound_notification")
def deliver_outbound_notification(notification_id: int) -> str:
    """
    Deliver one outbound notification immediately.

    The existing NotificationService row lock and sent/skipped guard make this
    safe to run alongside the one-minute fallback sweep.
    """
    from notifications.models import OutboundNotification
    from notifications.services import NotificationService

    notification = OutboundNotification.objects.filter(
        pk=notification_id
    ).first()
    if notification is None:
        return "missing"

    NotificationService.deliver(notification)
    notification.refresh_from_db(fields=["status"])
    return notification.status


__all__ = (
    "deliver_outbound_notification",
    "send_due_notifications",
    "notify_listing_expiring",
)
