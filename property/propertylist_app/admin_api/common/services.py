from .selectors import (
    get_recent_notifications,
    get_admin_profile_dropdown_data,
)


def get_notification_dropdown_data():
    notifications = get_recent_notifications(limit=10)

    return {
        "notifications": notifications,
        "unread_count": sum(
            1 for notification in notifications if not notification.is_read
        ),
    }
    
    
def get_profile_dropdown_data(user):
    return get_admin_profile_dropdown_data(user)    