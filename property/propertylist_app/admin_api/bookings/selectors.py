from django.db.models import Q

from propertylist_app.models import Booking


def get_booking_display_status(booking):
    if booking.is_deleted:
        return "deleted"

    if booking.status == Booking.STATUS_ACTIVE:
        return "confirmed"

    return booking.status


def get_booking_stats():
    return {
        "all_bookings": Booking.objects.count(),
        "confirmed_bookings": Booking.objects.filter(
            status=Booking.STATUS_ACTIVE,
            is_deleted=False,
        ).count(),
        "suspended_bookings": Booking.objects.filter(
            status=Booking.STATUS_SUSPENDED,
            is_deleted=False,
        ).count(),
        "cancelled_bookings": Booking.objects.filter(
            status=Booking.STATUS_CANCELLED,
            is_deleted=False,
        ).count(),
        "deleted_bookings": Booking.objects.filter(
            is_deleted=True,
        ).count(),
    }


def get_admin_bookings_queryset(params):
    qs = (
        Booking.objects
        .select_related("user", "room", "room__category")
        .all()
        .order_by("-created_at")
    )

    status_filter = (params.get("status") or "").strip().lower()

    if status_filter == "confirmed":
        qs = qs.filter(status=Booking.STATUS_ACTIVE, is_deleted=False)
    elif status_filter == "suspended":
        qs = qs.filter(status=Booking.STATUS_SUSPENDED, is_deleted=False)
    elif status_filter == "cancelled":
        qs = qs.filter(status=Booking.STATUS_CANCELLED, is_deleted=False)
    elif status_filter == "deleted":
        qs = qs.filter(is_deleted=True)

    property_type = (params.get("property_type") or "").strip()
    if property_type:
        qs = qs.filter(room__property_type__iexact=property_type)

    search = (params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(user__username__icontains=search)
            | Q(user__email__icontains=search)
            | Q(room__title__icontains=search)
        )

    return qs


def serialize_admin_booking(booking):
    return {
        "id": booking.id,
        "booking_id": f"BK{booking.id:04d}",
        "user": booking.user.get_full_name() or booking.user.username,
        "user_email": booking.user.email,
        "property_type": booking.room.property_type,
        "room_id": booking.room.id,
        "room_title": booking.room.title,
        "start": booking.start,
        "end": booking.end,
        "status": get_booking_display_status(booking),
        "is_deleted": booking.is_deleted,
        "created_at": booking.created_at,
    }