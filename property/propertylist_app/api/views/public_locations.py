from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer

from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import City, Room, UserProfile

from .common import _wrap_response_success, ok_response


class PublicCitySummarySerializer(serializers.ModelSerializer):
    """Public city-card payload. Property addresses/postcodes never appear here."""

    room_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = City
        fields = (
            "id",
            "name",
            "slug",
            "image",
            "image_alt",
            "room_count",
        )
        read_only_fields = fields


class PublicHomeSummarySerializer(serializers.Serializer):
    featured_rooms = RoomSerializer(many=True)
    latest_rooms = RoomSerializer(many=True)
    popular_cities = PublicCitySummarySerializer(many=True)
    stats = serializers.DictField()
    app_links = serializers.DictField()


def _city_room_count_filter(today):
    """Match the public search definition of a currently discoverable room."""

    return Q(
        rooms__is_deleted=False,
        rooms__status="active",
        rooms__is_available=True,
        rooms__paid_until__gte=today,
    )


def _public_cities_queryset(*, featured=None):
    today = timezone.localdate()
    qs = City.objects.filter(is_active=True)

    if featured is not None:
        qs = qs.filter(is_featured=featured)

    return (
        qs.annotate(
            room_count=Count(
                "rooms",
                filter=_city_room_count_filter(today),
                distinct=True,
            )
        )
        .order_by("display_order", "name")
    )


class HomePageView(APIView):
    """
    Public homepage data using the canonical City catalogue.

    City cards are sourced only from City records. Room.location is still used
    internally for property addresses/geocoding, but is never exposed as a city.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="CanonicalHomePageOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": PublicHomeSummarySerializer(),
                },
            )
        },
        description=(
            "Return homepage summary data. Popular city cards come from the "
            "canonical active/featured City catalogue, not Room.location."
        ),
    )
    def get(self, request):
        today = timezone.localdate()

        # Preserve the existing homepage room contract. Only city sourcing changes.
        base_rooms = (
            Room.objects.alive()
            .filter(status="active")
            .filter(Q(paid_until__isnull=True) | Q(paid_until__gte=today))
            .select_related("category", "property_owner")
        )

        featured_rooms_qs = base_rooms.order_by(
            "-avg_rating",
            "-number_rating",
            "-created_at",
        )[:6]
        latest_rooms_qs = base_rooms.order_by("-created_at")[:6]

        popular_cities = _public_cities_queryset(featured=True)[:12]

        payload = {
            "featured_rooms": featured_rooms_qs,
            "latest_rooms": latest_rooms_qs,
            "popular_cities": popular_cities,
            "stats": {
                "total_active_rooms": base_rooms.count(),
                "total_landlords": UserProfile.objects.filter(role="landlord").count(),
                "total_seekers": UserProfile.objects.filter(role="seeker").count(),
            },
            "app_links": {
                "ios": getattr(settings, "MOBILE_APP_IOS_URL", ""),
                "android": getattr(settings, "MOBILE_APP_ANDROID_URL", ""),
            },
        }

        serializer = PublicHomeSummarySerializer(
            payload,
            context={"request": request},
        )
        return ok_response(serializer.data, status_code=status.HTTP_200_OK)


class CityListView(APIView):
    """Return active canonical UK cities for the public city directory."""

    permission_classes = [AllowAny]
    pagination_class = StandardLimitOffsetPagination

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter canonical city names by case-insensitive substring.",
            ),
        ],
        responses={
            200: inline_serializer(
                name="CanonicalCityListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": PublicCitySummarySerializer(many=True),
                },
            )
        },
        description=(
            "List active canonical cities with city images and discoverable-room "
            "counts. Property addresses and postcodes are never returned as cities."
        ),
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()

        cities = _public_cities_queryset()
        if q:
            cities = cities.filter(name__icontains=q)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(cities, request, view=self)
        serializer = PublicCitySummarySerializer(
            page,
            many=True,
            context={"request": request},
        )

        return _wrap_response_success(
            paginator.get_paginated_response(serializer.data)
        )
