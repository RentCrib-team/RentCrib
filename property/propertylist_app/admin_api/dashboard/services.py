from .selectors import (
    get_total_users,
    get_active_listings_count,
)


def get_dashboard_overview_data():
    return {
        "total_users": get_total_users(),
        "active_listings": get_active_listings_count(),
        "pending_reviews": 0,
        "open_reports": 0,
        "payment_exceptions": 0,
        "unresolved_contact_messages": 0,
    }