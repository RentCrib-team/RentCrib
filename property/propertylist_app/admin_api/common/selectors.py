from propertylist_app.models import Notification


def get_recent_notifications(limit=10):
    return (
        Notification.objects.select_related("user")
        .order_by("-created_at")[:limit]
    )
    
    
def get_admin_profile_dropdown_data(user):
    profile = getattr(user, "profile", None)

    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "admin_role": getattr(user, "admin_role", ""),
        "avatar": (
            profile.avatar.url
            if profile and profile.avatar
            else None
        ),
        "email_verified": getattr(user, "email_verified", False),
        "phone_verified": getattr(user, "phone_verified", False),
    }    