from propertylist_app.models import Notification


def get_recent_notifications(limit=10):
    return (
        Notification.objects.select_related("user")
        .order_by("-created_at")[:limit]
    )