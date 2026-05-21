from .selectors import get_recent_notifications


def get_notification_dropdown_data():
    notifications = get_recent_notifications(limit=10)

    return {
        "notifications": notifications,
        "unread_count": sum(
            1 for notification in notifications if not notification.is_read
        ),
    }