from django.contrib.auth import get_user_model

from propertylist_app.models import (
    Room,
    Report,
    Payment,
    ContactMessage,
    RoomImage,
)

User = get_user_model()


def get_total_users():
    return User.objects.count()


def get_active_listings_count():
    return Room.objects.filter(
        is_deleted=False,
        status="active",
    ).count()


def get_pending_moderation_count():
    return RoomImage.objects.filter(
        status="pending",
    ).count()


def get_open_reports_count():
    return Report.objects.filter(
        status="open",
    ).count()


def get_payment_exceptions_count():
    return Payment.objects.filter(
        status__in=[
            "failed",
            "requires_payment_method",
        ]
    ).count()


def get_unresolved_contact_messages_count():
    return ContactMessage.objects.count()