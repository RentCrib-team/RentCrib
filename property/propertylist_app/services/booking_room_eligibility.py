"""Server-side eligibility guard for new viewing bookings."""

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from propertylist_app.models import AvailabilitySlot, Room


_INSTALLED = False
_ERROR = "Room is not available for booking."


def bookable_room_queryset():
    """Rooms for which RentCrib may accept a new viewing booking."""
    return Room.objects.alive().filter(
        status=Room.Lifecycle.ACTIVE,
        is_available=True,
        paid_until__gte=timezone.localdate(),
    )


def _existing_room_id_for_slot(slot_id):
    if not slot_id:
        return None
    return (
        AvailabilitySlot.objects
        .filter(pk=slot_id)
        .values_list("room_id", flat=True)
        .first()
    )


def _ensure_existing_room_is_bookable(room_id):
    """
    Reject an existing room that is not currently bookable.

    Missing room/slot identifiers are deliberately left to the existing view
    validation so this guard changes only lifecycle eligibility behaviour.
    """
    if not room_id:
        return

    if not Room.objects.filter(pk=room_id).exists():
        return

    if not bookable_room_queryset().filter(pk=room_id).exists():
        raise ValidationError({"room": _ERROR})


def install_booking_room_eligibility_guard():
    """Apply the same room lifecycle gate to every booking-creation endpoint."""
    global _INSTALLED
    if _INSTALLED:
        return

    from propertylist_app.api.views import bookings as booking_views

    # POST /bookings/create/ is an @api_view function. Patch its generated
    # DRF view-class POST handler so authentication/parsing/decorators remain
    # exactly as they already are, while preflight cannot approve a private or
    # expired room.
    preflight_view = booking_views.create_booking
    original_preflight_post = preflight_view.cls.post

    def guarded_preflight_post(self, request, *args, **kwargs):
        _ensure_existing_room_is_bookable(request.data.get("room"))
        return original_preflight_post(self, request, *args, **kwargs)

    preflight_view.cls.post = guarded_preflight_post

    # Legacy/mobile viewing endpoint: slot_id OR room_id.
    original_viewing_post = booking_views.CreateViewingBookingView.post

    def guarded_viewing_post(self, request, *args, **kwargs):
        slot_id = request.data.get("slot_id")
        room_id = _existing_room_id_for_slot(slot_id) if slot_id else request.data.get("room_id")
        _ensure_existing_room_is_bookable(room_id)
        return original_viewing_post(self, request, *args, **kwargs)

    booking_views.CreateViewingBookingView.post = guarded_viewing_post

    # Canonical POST /bookings/: slot OR direct room booking.
    original_perform_create = booking_views.BookingListCreateView.perform_create

    def guarded_perform_create(self, serializer):
        slot_id = self.request.data.get("slot")
        room_id = _existing_room_id_for_slot(slot_id) if slot_id else self.request.data.get("room")
        _ensure_existing_room_is_bookable(room_id)
        return original_perform_create(self, serializer)

    booking_views.BookingListCreateView.perform_create = guarded_perform_create

    _INSTALLED = True
