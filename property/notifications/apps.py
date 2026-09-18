# notifications/apps.py
from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


logger = logging.getLogger(__name__)


def ensure_notification_periodic_tasks(**kwargs) -> None:
    """
    Create/repair the django-celery-beat PeriodicTask rows for notifications.

    IMPORTANT:
    - We set queue + routing_key explicitly, otherwise tasks can sit "queued" forever
      depending on how the worker is consuming.
    - We run this on post_migrate to avoid DB queries during app initialization.
    """
    from django.utils import timezone
    from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks

    tz = getattr(settings, "TIME_ZONE", "UTC")

    # Every minute
    every_minute, _ = CrontabSchedule.objects.get_or_create(
        minute="*",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=tz,
    )

    PeriodicTask.objects.update_or_create(
        name="send-due-notifications-every-minute",
        defaults={
            "task": "notifications.tasks.send_due_notifications",
            "crontab": every_minute,
            "enabled": True,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "args": "[]",
            "kwargs": "{}",
        },
           
    )

    PeriodicTask.objects.update_or_create(
        name="notify-upcoming-bookings-every-minute",
        defaults={
            "task": "propertylist_app.services.tasks.notify_upcoming_bookings",
            "crontab": every_minute,
            "enabled": True,
            "one_off": False,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "args": "[5]",
            "kwargs": "{}",
            "description": (
                "Checks every minute for viewings starting within the next "
                "5 minutes and queues seeker reminders."
            ),
        },
    )

    PeriodicTask.objects.update_or_create(
        name="tenancy-prompts-sweep-every-minute",
        defaults={
            "task": "propertylist_app.tasks.task_tenancy_prompts_sweep",
            "crontab": every_minute,
            "interval": None,
            "enabled": True,
            "one_off": False,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "args": "[]",
            "kwargs": "{}",
            "description": (
                "Checks every minute for due tenancy reminders "
                "and review-window transitions."
            ),
        },
    )

    # Remove the obsolete disabled schedule from previous deployments.
    PeriodicTask.objects.filter(
        name="tenancy_prompts_sweep (1m)"
    ).delete()





    # OPTIONAL: keep/repair your daily listing expiry task (if you want it here too)
    # daily_7am, _ = CrontabSchedule.objects.get_or_create(
    #     minute="0", hour="7", day_of_week="*", day_of_month="*", month_of_year="*", timezone=tz
    # )
    # PeriodicTask.objects.update_or_create(
    #     name="notify-listing-expiring-daily-7am",
    #     defaults={
    #         "task": "notifications.tasks.notify_listing_expiring",
    #         "crontab": daily_7am,
    #         "enabled": True,
    #         "queue": "celery",
    #         "routing_key": "celery",
    #         "exchange": None,
    #         "args": "[]",
    #         "kwargs": "{}",
    #     },
    # )

    # Tell django-celery-beat to reload its database schedule.
    PeriodicTasks.objects.update_or_create(
        ident=1,
        defaults={"last_update": timezone.now()},
    )


def enqueue_immediate_outbound_email(sender, instance, created, **kwargs) -> None:
    """
    Queue newly-created email notifications for immediate Celery delivery.

    Future-scheduled notifications are left for the existing periodic sweep.
    Tests opt out by default so existing unit tests can create notification
    rows without unexpectedly invoking Celery.
    """
    if not created or getattr(settings, "TESTING", False):
        return

    from django.db import transaction
    from django.utils import timezone

    from notifications.models import NotificationTemplate, OutboundNotification

    if instance.channel != NotificationTemplate.CHANNEL_EMAIL:
        return

    if instance.status != OutboundNotification.STATUS_QUEUED:
        return

    if instance.scheduled_for and instance.scheduled_for > timezone.now():
        return

    notification_id = instance.pk

    def _dispatch() -> None:
        from notifications.tasks import deliver_outbound_notification

        try:
            deliver_outbound_notification.delay(notification_id)
        except Exception:
            # The periodic sweep remains the recovery path if the broker is
            # temporarily unavailable. Never break the business request after
            # its database transaction has already committed.
            logger.exception(
                "Immediate email enqueue failed; periodic fallback will retry",
                extra={"notification_id": notification_id},
            )

    transaction.on_commit(_dispatch)


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self) -> None:
        from django.db.models.signals import post_save

        from notifications.models import OutboundNotification

        post_migrate.connect(
            ensure_notification_periodic_tasks,
            sender=self,
        )
        post_save.connect(
            enqueue_immediate_outbound_email,
            sender=OutboundNotification,
            dispatch_uid="notifications.immediate_outbound_email",
        )