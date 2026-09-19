"""Query optimization for room detail retrieval."""

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from propertylist_app.api.views.rooms import RoomDetailAV
from propertylist_app.models import Room, RoomImage, Tenancy
from propertylist_app.services.public_room_visibility import _public_rooms_queryset


_INSTALLED = False


def _optimized_get_room(self, request, pk):
    """Fetch participant-private rooms or a genuinely public room with related data joined."""
    related = (
        "category",
        "property_owner",
        "property_owner__profile",
    )

    if request.user.is_authenticated:
        private_room = (
            Room.objects.filter(
                Q(property_owner=request.user)
                | Q(
                    tenancies__in=Tenancy.objects.filter(
                        Q(landlord=request.user) | Q(tenant=request.user),
                    ),
                ),
                pk=pk,
                is_deleted=False,
            )
            .select_related(*related)
            .prefetch_related(
                Prefetch(
                    "roomimage_set",
                    queryset=RoomImage.objects.filter(
                        status__in=["approved", "pending", "rejected"],
                    ).order_by("id"),
                )
            )
            .distinct()
            .first()
        )

        if private_room is not None:
            return private_room

    return get_object_or_404(
        _public_rooms_queryset().select_related(*related).prefetch_related(
            Prefetch(
                "roomimage_set",
                queryset=RoomImage.objects.filter(
                    status__in=["approved", "pending", "rejected"],
                ).order_by("id"),
            )
        ),
        pk=pk,
    )


def install_room_detail_query_optimization():
    """Install the optimized room-detail lookup once at application startup."""
    global _INSTALLED

    if _INSTALLED:
        return

    RoomDetailAV._get_room = _optimized_get_room
    _INSTALLED = True
