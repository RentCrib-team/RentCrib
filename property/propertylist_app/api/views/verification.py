from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from propertylist_app.models import LandlordVerificationRequest, UserProfile
from propertylist_app.api.serializers import LandlordVerificationRequestSerializer
from .common import ok_response, error_response
from drf_spectacular.utils import extend_schema

class MyLandlordVerificationRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Verification"],
        responses=LandlordVerificationRequestSerializer,
    )
    def get(self, request):
        latest_request = (
            LandlordVerificationRequest.objects
            .filter(user=request.user)
            .order_by("-created_at")
            .first()
        )

        if not latest_request:
            return ok_response(
                message="No landlord verification request found.",
                data=None,
            )

        serializer = LandlordVerificationRequestSerializer(latest_request)
        return ok_response(
            message="Landlord verification request retrieved.",
            data=serializer.data,
        )

    @extend_schema(
        tags=["Verification"],
        request=LandlordVerificationRequestSerializer,
        responses=LandlordVerificationRequestSerializer,
    )
    def post(self, request):
        profile = getattr(request.user, "profile", None)

        if not profile:
            return error_response(
                message="User profile not found.",
                code="profile_not_found",
                status_code=400,
            )

        if profile.role != "landlord":
            return error_response(
                message="Only landlords can request advertiser verification.",
                code="landlord_required",
                status_code=403,
            )

        if profile.advertiser_verified:
            return error_response(
                message="This landlord is already verified.",
                code="already_verified",
                status_code=400,
            )

        existing_pending = LandlordVerificationRequest.objects.filter(
            user=request.user,
            status=LandlordVerificationRequest.STATUS_PENDING,
        ).first()

        if existing_pending:
            serializer = LandlordVerificationRequestSerializer(existing_pending)
            return ok_response(
                message="A landlord verification request is already pending.",
                data=serializer.data,
            )

        serializer = LandlordVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_request = serializer.save(
            user=request.user,
            status=LandlordVerificationRequest.STATUS_PENDING,
        )

        return ok_response(
            message="Landlord verification request submitted.",
            data=LandlordVerificationRequestSerializer(verification_request).data,
            status_code=201,
        )