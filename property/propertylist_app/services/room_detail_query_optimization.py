"""Query optimization for room detail retrieval."""

from django.db.models import Q
from django.shortcuts import get_object_or_404

from propertylist_app.api.views.rooms import RoomDetailAV
from propertylist_app.models import Room
from propertylist_app.services.public_room_visibility import _public_rooms_queryset


_INSTALLED = False


def _optimized_get_room(self, request, pk):
    """Fetch a room when it is public or belongs to this tenancy participant."""
    related = (
        "category",
        "property_owner",
        "property_owner__profile",
    )

    if request.user.is_authenticated:
        participant_room = (
            Room.objects.filter(
                pk=pk,
                is_deleted=False,
            )
            .filter(
                Q(property_owner=request.user)
                | Q(tenancies__landlord=request.user)
                | Q(tenancies__tenant=request.user)
            )
            .select_related(*related)
            .distinct()
            .first()
        )

        if participant_room is not None:
            return participant_room

    return get_object_or_404(
        _public_rooms_queryset().select_related(*related),
        pk=pk,
    )


def install_room_detail_query_optimization():
    """Install the optimized room-detail lookup once at application startup."""
    global _INSTALLED

    if _INSTALLED:
        return

    RoomDetailAV._get_room = _optimized_get_room
    _INSTALLED = True
