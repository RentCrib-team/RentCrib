from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from propertylist_app.admin_api.permissions import IsAdminUser
from propertylist_app.api.views.common import ok_response, error_response
from propertylist_app.models import LandlordVerificationRequest, UserProfile

from .serializers import (
    AdminLandlordVerificationActionSerializer,
    AdminLandlordVerificationRequestSerializer,
)


class IsSupportOrSuperAdmin(IsAdminUser):
    ALLOWED_ADMIN_ROLES = {
        "super_admin",
        "support_admin",
    }


class AdminLandlordVerificationListView(APIView):
    permission_classes = [IsSupportOrSuperAdmin]

    @extend_schema(
        tags=["Admin - Support"],
        responses=AdminLandlordVerificationRequestSerializer(many=True),
    )
    def get(self, request):
        status_filter = request.query_params.get("status")

        queryset = (
            LandlordVerificationRequest.objects
            .select_related("user", "reviewed_by")
            .order_by("-created_at")
        )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        serializer = AdminLandlordVerificationRequestSerializer(queryset, many=True)

        return ok_response(
            message="Landlord verification requests retrieved.",
            data=serializer.data,
        )


class AdminLandlordVerificationActionView(APIView):
    permission_classes = [IsSupportOrSuperAdmin]

    @extend_schema(
        tags=["Admin - Support"],
        request=AdminLandlordVerificationActionSerializer,
        responses=AdminLandlordVerificationRequestSerializer,
    )
    def post(self, request, request_id):
        verification_request = get_object_or_404(
            LandlordVerificationRequest,
            id=request_id,
        )

        serializer = AdminLandlordVerificationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        rejection_reason = serializer.validated_data.get("rejection_reason", "").strip()

        if verification_request.status != LandlordVerificationRequest.STATUS_PENDING:
            return error_response(
                message="Only pending verification requests can be reviewed.",
                code="verification_request_not_pending",
                status_code=400,
            )

        profile, _ = UserProfile.objects.get_or_create(user=verification_request.user)

        if action == "approve":
            verification_request.status = LandlordVerificationRequest.STATUS_APPROVED
            verification_request.reviewed_by = request.user
            verification_request.reviewed_at = timezone.now()
            verification_request.rejection_reason = ""
            verification_request.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            profile.advertiser_verified = True
            profile.save(update_fields=["advertiser_verified"])

            return ok_response(
                message="Landlord verification request approved.",
                data=AdminLandlordVerificationRequestSerializer(verification_request).data,
            )

        if action == "reject":
            if not rejection_reason:
                return error_response(
                    message="Rejection reason is required when rejecting a verification request.",
                    code="rejection_reason_required",
                    status_code=400,
                )

            verification_request.status = LandlordVerificationRequest.STATUS_REJECTED
            verification_request.reviewed_by = request.user
            verification_request.reviewed_at = timezone.now()
            verification_request.rejection_reason = rejection_reason
            verification_request.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            return ok_response(
                message="Landlord verification request rejected.",
                data=AdminLandlordVerificationRequestSerializer(verification_request).data,
            )