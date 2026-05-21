from django.contrib.auth.models import User

from propertylist_app.models import UserProfile


def get_admin_users_queryset():
    return (
        User.objects.select_related("profile")
        .filter(
            is_staff=True,
            profile__admin_role__isnull=False,
        )
        .exclude(profile__admin_role="")
        .order_by("first_name", "last_name", "username")
    )
    
    
def get_admin_role_permissions():
    return {
        "super_admin": [
            "full_access",
            "manage_admins",
            "manage_payments",
            "manage_moderation",
            "manage_operations",
            "manage_support",
        ],
        "ops_admin": [
            "manage_operations",
            "manage_listings",
            "manage_bookings",
            "manage_tenancies",
        ],
        "moderator": [
            "manage_moderation",
            "review_reports",
            "approve_listings",
        ],
        "finance_admin": [
            "manage_payments",
            "view_transactions",
            "manage_refunds",
        ],
        "support_admin": [
            "manage_support",
            "manage_messages",
            "assist_users",
        ],
    }    
    