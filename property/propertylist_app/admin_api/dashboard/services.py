from .selectors import (
    get_total_users,
    get_active_listings_count,
    get_pending_moderation_count,
    get_open_reports_count,
    get_payment_exceptions_count,
    get_unresolved_contact_messages_count,
)


def get_dashboard_overview_data():
    return {
        "total_users": get_total_users(),
        "active_listings": get_active_listings_count(),
        "pending_reviews": get_pending_moderation_count(),
        "open_reports": get_open_reports_count(),
        "payment_exceptions": get_payment_exceptions_count(),
        "unresolved_contact_messages": (
            get_unresolved_contact_messages_count()
        ),
    }