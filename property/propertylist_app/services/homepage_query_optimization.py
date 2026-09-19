from django.conf import settings
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status

from propertylist_app.api.views.common import ok_response
from propertylist_app.models import Room, RoomImage, UserProfile


def install_homepage_owner_profile_query_optimization():
    """Ensure HomePageView fetches landlord profiles with each room query."""
    from propertylist_app.api.views import public as public_views

    if getattr(public_views.HomePageView, "_owner_profile_query_optimized", False):
        return

    def get(self, request):
        cached = self._get_cached_response(request)
        if cached is not None:
            return cached

        today = timezone.now().date()

        base_rooms = (
            Room.objects.alive()
            .filter(status="active")
            .filter(Q(paid_until__isnull=True) | Q(paid_until__gte=today))
            .select_related("category", "property_owner", "property_owner__profile")
            .prefetch_related(
                Prefetch(
                    "roomimage_set",
                    queryset=RoomImage.objects.filter(
                        status__in=["approved", "pending", "rejected"],
                    ).order_by("id"),
                )
            )
        )

        featured_rooms_qs = base_rooms.order_by(
            "-avg_rating",
            "-number_rating",
            "-created_at",
        )[:6]
        latest_rooms_qs = (
            base_rooms
            .annotate(
                _latest_listing_at=Coalesce(
                    "relisted_at",
                    "created_at",
                )
            )
            .order_by("-_latest_listing_at")[:6]
        )

        city_rows = (
            base_rooms
            .exclude(location__isnull=True)
            .exclude(location__exact="")
            .values("location")
            .annotate(room_count=Count("id"))
            .order_by("-room_count", "location")[:12]
        )
        popular_cities = [
            {"name": row["location"], "room_count": row["room_count"]}
            for row in city_rows
        ]

        stats = {
            "total_active_rooms": base_rooms.count(),
            "total_landlords": UserProfile.objects.filter(role="landlord").count(),
            "total_seekers": UserProfile.objects.filter(role="seeker").count(),
        }

        app_links = {
            "ios": getattr(settings, "MOBILE_APP_IOS_URL", ""),
            "android": getattr(settings, "MOBILE_APP_ANDROID_URL", ""),
        }

        payload = {
            "featured_rooms": featured_rooms_qs,
            "latest_rooms": latest_rooms_qs,
            "popular_cities": popular_cities,
            "stats": stats,
            "app_links": app_links,
        }

        serializer_class = public_views.HomeSummarySerializer
        if request.query_params.get("compact") == "1":
            from propertylist_app.api.serializers import CompactHomeSummarySerializer

            serializer_class = CompactHomeSummarySerializer

        serializer = serializer_class(
            payload,
            context={"request": request},
        )
        response = ok_response(serializer.data, status_code=status.HTTP_200_OK)
        return self._store_cached_response(request, response)

    public_views.HomePageView.get = get
    public_views.HomePageView._owner_profile_query_optimized = True
