import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

from celery import Celery
from celery.schedules import crontab

app = Celery("property")
app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks([
    "propertylist_app",
    "propertylist_app.notifications",
])

# Register compatibility bridge task names and listing lifecycle tasks that
# live outside Celery's conventional tasks.py module.
app.conf.imports = tuple(app.conf.get("imports", ())) + (
    "notifications.tasks",
    "propertylist_app.city_image_tasks",
    "propertylist_app.listing_expiry_tasks",
)

app.conf.beat_schedule = {
    # Notifications
    "send-due-notifications-every-minute": {
        "task": "notifications.tasks.send_due_notifications",
        "schedule": crontab(minute="*"),
    },

    # Listing advertising expiry automation is intentionally disabled.
    # Do not schedule either the accelerated 15-minute warning or the
    # 20-minute expiry/free-period transition. Viewing and tenancy QA timers
    # below are separate and remain enabled.

    "notify-upcoming-bookings-every-minute": {
        "task": "propertylist_app.services.tasks.notify_upcoming_bookings",
        "schedule": crontab(minute="*"),
        "args": (5,),
    },
    "notify-completed-viewings-every-minute": {
        "task": "propertylist_app.notifications.tasks.notify_completed_viewings",
        "schedule": crontab(minute="*"),
    },

    # Accounts
    "delete-scheduled-accounts-daily-03:10": {
        "task": "propertylist_app.delete_scheduled_accounts",
        "schedule": crontab(hour=3, minute=10),
    },

    # Reviews
    "refresh-room-ratings-nightly-02:30": {
        "task": "propertylist_app.refresh_room_ratings_nightly",
        "schedule": crontab(hour=2, minute=30),
    },

    # ---------------------------------------------------------
    # TENANCY SWEEPS
    # ---------------------------------------------------------

    # Production schedule — disabled while QA uses accelerated timers.
    # "tenancy-prompts-sweep-daily-03:20": {
    #     "task": "propertylist_app.tasks.task_tenancy_prompts_sweep",
    #     "schedule": crontab(hour=3, minute=20),
    # },

    # QA schedule — required for the accelerated tenancy lifecycle tests.
    "tenancy-prompts-sweep-every-minute": {
        "task": "propertylist_app.tasks.task_tenancy_prompts_sweep",
        "schedule": crontab(minute="*"),
    },

    # Production real-calendar reconciliation — disabled while the accelerated
    # QA tenancy lifecycle is active. Running this task alongside the minute
    # sweep creates a second clock: it can end live tenancies from their real
    # tenancy dates and can backfill schedule fields from compute_review_window()
    # instead of preserving the chained QA Timer 2 -> reminder -> review flow.
    # Restore this schedule only when the tenancy lifecycle returns to the
    # production date-based timing rules.
    # "refresh-tenancy-status-and-review-windows-daily": {
    #     "task": "propertylist_app.tasks.task_refresh_tenancy_status_and_review_windows",
    #     "schedule": 60 * 60 * 24,
    # },
}


@app.on_after_finalize.connect
def install_city_image_autofill_schedule(sender, **kwargs):
    sender.add_periodic_task(
        crontab(minute="*/10"),
        sender.signature("propertylist_app.enqueue_missing_city_images"),
        name="autofill-missing-city-images",
        expires=9 * 60,
    )
