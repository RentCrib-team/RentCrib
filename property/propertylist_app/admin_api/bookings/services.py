from django.utils import timezone
from rest_framework.exceptions import ValidationError

from propertylist_app.models import Booking

from .selectors import (
    get_admin_bookings_queryset,
    get_booking_stats,
    serialize_admin_booking,
)


def get_admin_booking_overview_data(params):
    queryset = get_admin_bookings_queryset(params)

    return {
        "stats": get_booking_stats(),
        "bookings": [
            serialize_admin_booking(booking)
            for booking in queryset
        ],
    }


def update_admin_booking_action(booking_id, action):
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        raise ValidationError("Booking not found.")

    if action == "suspend":
        if booking.is_deleted:
            raise ValidationError("Deleted bookings cannot be suspended.")
        if booking.status != Booking.STATUS_ACTIVE:
            raise ValidationError("Only confirmed bookings can be suspended.")

        booking.status = Booking.STATUS_SUSPENDED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        message = "Booking suspended successfully."

    elif action == "cancel":
        if booking.is_deleted:
            raise ValidationError("Deleted bookings cannot be cancelled.")
        if booking.status == Booking.STATUS_CANCELLED:
            raise ValidationError("Booking is already cancelled.")

        booking.status = Booking.STATUS_CANCELLED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        message = "Booking cancelled successfully."

    elif action == "soft_delete":
        if booking.is_deleted:
            raise ValidationError("Booking is already deleted.")

        booking.soft_delete()
        message = "Booking soft deleted successfully."

    elif action == "restore":
        if not booking.is_deleted:
            raise ValidationError("Only deleted bookings can be restored.")

        booking.restore()
        message = "Booking restored successfully."

    else:
        raise ValidationError("Invalid booking action.")

    return {
        "message": message,
        "booking": {
            "id": booking.id,
            "status": (
                "confirmed"
                if booking.status == Booking.STATUS_ACTIVE
                else booking.status
            ),
            "is_deleted": booking.is_deleted,
        },
    }