from django.contrib.auth import get_user_model
from django.db.models import Avg
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.serializers import ReviewSerializer
from propertylist_app.models import Review, UserProfile

from .common import ok_response


MemberProfilePageDataSerializer = inline_serializer(
    name="MemberProfilePageData",
    fields={
        "id": serializers.IntegerField(),
        "display_name": serializers.CharField(),
        "username": serializers.CharField(),
        "date_joined": serializers.DateTimeField(),
        "avatar": serializers.URLField(allow_blank=True, allow_null=True, required=False),
        "role": serializers.ChoiceField(choices=("landlord", "seeker")),
        "role_detail": serializers.CharField(allow_blank=True, allow_null=True, required=False),
        "occupation": serializers.CharField(allow_blank=True, required=False),
        "about_you": serializers.CharField(allow_blank=True, required=False),
        "age": serializers.IntegerField(allow_null=True, required=False),
        "location": serializers.CharField(allow_blank=True, required=False),
        "total_reviews": serializers.IntegerField(),
        "overall_rating": serializers.FloatField(allow_null=True),
        "landlord_reviews_count": serializers.IntegerField(),
        "landlord_rating_average": serializers.FloatField(allow_null=True),
        "tenant_reviews_count": serializers.IntegerField(),
        "tenant_rating_average": serializers.FloatField(allow_null=True),
        "reviews_preview": ReviewSerializer(many=True),
        "landlord_verified": serializers.BooleanField(),
    },
)


def _postcode_area(postcode):
    compact = "".join((postcode or "").upper().split())
    if len(compact) <= 3:
        return ""
    return f"{compact[:-3]} area"


class MemberProfilePageView(APIView):
    """Read-only profile for another signed-in RentCrib member."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "MemberProfilePageResponse",
                MemberProfilePageDataSerializer,
            ),
            400: OpenApiResponse(description="Invalid role."),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="User not found."),
        },
    )
    def get(self, request, user_id):
        user = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
        profile, _ = UserProfile.objects.get_or_create(user=user)

        requested_role = (
            request.query_params.get("role") or profile.role or "seeker"
        ).strip().lower()
        if requested_role not in {"landlord", "seeker"}:
            raise serializers.ValidationError(
                {"role": "Role must be either 'landlord' or 'seeker'."}
            )

        reviews = Review.objects.filter(
            reviewee_id=user.id,
            reveal_at__isnull=False,
            reveal_at__lte=timezone.now(),
            active=True,
        )
        landlord_reviews = reviews.filter(role=Review.ROLE_TENANT_TO_LANDLORD)
        tenant_reviews = reviews.filter(role=Review.ROLE_LANDLORD_TO_TENANT)

        landlord_count = landlord_reviews.count()
        tenant_count = tenant_reviews.count()
        landlord_average = landlord_reviews.aggregate(a=Avg("overall_rating")).get("a")
        tenant_average = tenant_reviews.aggregate(a=Avg("overall_rating")).get("a")

        if requested_role == "landlord":
            role_reviews = landlord_reviews
            total_reviews = landlord_count
            overall_rating = landlord_average
        else:
            role_reviews = tenant_reviews
            total_reviews = tenant_count
            overall_rating = tenant_average

        reviews_preview = ReviewSerializer(
            role_reviews.order_by("-submitted_at")[:2],
            many=True,
            context={"request": request},
        ).data

        age = None
        if profile.date_of_birth:
            today = timezone.now().date()
            dob = profile.date_of_birth
            age = today.year - dob.year - (
                (today.month, today.day) < (dob.month, dob.day)
            )

        avatar = None
        if profile.avatar:
            try:
                avatar = request.build_absolute_uri(profile.avatar.url)
            except (AttributeError, ValueError):
                avatar = None

        display_name = user.get_full_name().strip() or user.username

        payload = {
            "id": user.id,
            "display_name": display_name,
            "username": user.username,
            "date_joined": user.date_joined,
            "avatar": avatar,
            "role": requested_role,
            "role_detail": profile.role_detail or "",
            "occupation": profile.occupation or "",
            "about_you": profile.about_you or "",
            "age": age,
            "location": _postcode_area(profile.postcode),
            "total_reviews": total_reviews,
            "overall_rating": overall_rating,
            "landlord_reviews_count": landlord_count,
            "landlord_rating_average": landlord_average,
            "tenant_reviews_count": tenant_count,
            "tenant_rating_average": tenant_average,
            "reviews_preview": reviews_preview,
            "landlord_verified": bool(
                getattr(profile, "advertiser_verified", False)
            ),
        }

        return ok_response(
            payload,
            message="Member profile retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )
