from django.conf import settings
from django.utils import timezone
from rest_framework import status

from propertylist_app.models import Room, UserProfile


def _public_rooms_queryset():
    """Single public-advert contract used by room discovery surfaces."""
    return Room.objects.alive().filter(
        status=Room.Lifecycle.ACTIVE,
        is_available=True,
        paid_until__gte=timezone.localdate(),
    )


def install_public_room_visibility_contract():
    """
    Make every public room-listing surface use the same advert eligibility rule.

    A room is public only when it is active, available, not deleted, and its
    paid advertising period has not expired. Owner/private listing views are
    intentionally untouched.
    """
    from propertylist_app.api.pagination import StandardLimitOffsetPagination
    from propertylist_app.api.serializers import RoomSerializer
    from propertylist_app.api.views.common import ok_response, _wrap_response_success
    from propertylist_app.api.views.rooms import (
        RoomAV,
        RoomListAlt,
        RoomListGV,
        _optimised_room_read_queryset,
    )
    from propertylist_app.api.views import public_locations

    if getattr(RoomAV, "_public_visibility_contract_installed", False):
        return

    def room_list_get(self, request, *args, **kwargs):
        cached = self._get_cached_response(request)
        if cached is not None:
            return cached

        qs = _optimised_room_read_queryset(
            _public_rooms_queryset().order_by("-id"),
            request,
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = RoomSerializer(
            page,
            many=True,
            context={"request": request},
        )
        response = _wrap_response_success(
            paginator.get_paginated_response(serializer.data)
        )
        return self._store_cached_response(request, response)

    def room_list_gv_queryset(self):
        return _public_rooms_queryset()

    def room_list_alt_queryset(self):
        return _public_rooms_queryset().order_by("-avg_rating")

    def homepage_get(self, request):
        base_rooms = _public_rooms_queryset().select_related(
            "category",
            "property_owner",
            "property_owner__profile",
        )

        featured_rooms_qs = base_rooms.order_by(
            "-avg_rating",
            "-number_rating",
            "-created_at",
        )[:6]
        latest_rooms_qs = base_rooms.order_by("-created_at")[:6]
        popular_cities = public_locations._public_cities_queryset(
            featured=True
        )[:12]

        payload = {
            "featured_rooms": featured_rooms_qs,
            "latest_rooms": latest_rooms_qs,
            "popular_cities": popular_cities,
            "stats": {
                "total_active_rooms": base_rooms.count(),
                "total_landlords": UserProfile.objects.filter(
                    role="landlord"
                ).count(),
                "total_seekers": UserProfile.objects.filter(
                    role="seeker"
                ).count(),
            },
            "app_links": {
                "ios": getattr(settings, "MOBILE_APP_IOS_URL", ""),
                "android": getattr(settings, "MOBILE_APP_ANDROID_URL", ""),
            },
        }

        serializer = public_locations.PublicHomeSummarySerializer(
            payload,
            context={"request": request},
        )
        return ok_response(
            serializer.data,
            status_code=status.HTTP_200_OK,
        )

    RoomAV.get = room_list_get
    RoomListGV.get_queryset = room_list_gv_queryset
    RoomListAlt.get_queryset = room_list_alt_queryset
    public_locations.HomePageView.get = homepage_get

    RoomAV._public_visibility_contract_installed = True
