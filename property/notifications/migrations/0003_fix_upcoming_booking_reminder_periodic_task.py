from __future__ import annotations

from django.db import migrations
from django.utils import timezone


def repair_upcoming_booking_reminder_task(apps, schema_editor):
    PeriodicTask = apps.get_model(
        "django_celery_beat",
        "PeriodicTask",
    )
    CrontabSchedule = apps.get_model(
        "django_celery_beat",
        "CrontabSchedule",
    )
    PeriodicTasks = apps.get_model(
        "django_celery_beat",
        "PeriodicTasks",
    )

    every_minute, _ = CrontabSchedule.objects.get_or_create(
        minute="*",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Europe/London",
    )

    PeriodicTask.objects.update_or_create(
        name="notify-upcoming-bookings-every-minute",
        defaults={
            "task": (
                "propertylist_app.services.tasks."
                "notify_upcoming_bookings"
            ),
            "crontab": every_minute,
            "enabled": True,
            "one_off": False,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "priority": None,
            "headers": {},
            "args": "[5]",
            "kwargs": "{}",
            "description": (
                "Checks every minute for viewings starting within the next "
                "5 minutes and queues seeker reminders."
            ),
        },
    )

    PeriodicTasks.objects.update_or_create(
        ident=1,
        defaults={
            "last_update": timezone.now(),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "notifications",
            "0002_fix_send_due_notifications_periodic_task",
        ),
        (
            "django_celery_beat",
            "0018_improve_crontab_helptext",
        ),
    ]

    operations = [
        migrations.RunPython(
            repair_upcoming_booking_reminder_task,
            reverse_code=migrations.RunPython.noop,
        ),
    ]