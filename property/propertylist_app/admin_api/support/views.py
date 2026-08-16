from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from propertylist_app.admin_api.permissions import IsAdminUser
from propertylist_app.api.views.common import ok_response, error_response


from .serializers import (
    AdminLandlordVerificationActionSerializer,
    AdminLandlordVerificationRequestSerializer,
)
from django.utils import timezone

from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
)

from propertylist_app.models import (
    LandlordVerificationRequest,
    Notification,
    UserProfile,
)

from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event



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

            # -----------------------------------------------------
            # Verification approved:
            # Bell + realtime Bell + email.
            # No inbox/envelope message.
            # -----------------------------------------------------
            notification = Notification.objects.create(
                user=verification_request.user,
                type="identity_verification_approved",
                target_type="identity_verification",
                target_id=verification_request.id,
                title="Identity verified",
                body=(
                    "Your identity verification has been approved."
                ),
            )

            push_user_realtime_event(
                verification_request.user.id,
                "new_notification",
                {
                    "kind": "identity_verification_approved",
                    "notification_id": notification.id,
                    "target_type": "identity_verification",
                    "target_id": verification_request.id,
                },
            )

            template_exists = (
                NotificationTemplate.objects.filter(
                    key="identity_verification.approved",
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    is_active=True,
                ).exists()
            )

            if template_exists:
                OutboundNotification.objects.create(
                    user=verification_request.user,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="identity_verification.approved",
                    scheduled_for=timezone.now(),
                    context={
                        "user_name": (
                            verification_request.user.first_name
                            or verification_request.user.username
                        ),

                        # Permanent frontend verification route.
                        "dashboard_url": build_absolute_url(
                            "/identity-verification",
                            force_login=True,
                        ),

                        # Existing support route.
                        "support_url": build_absolute_url(
                            "/contact",
                            force_login=False,
                        ),

                        "current_year": timezone.now().year,
                        "verification_request_id": verification_request.id,
                    },
                )



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


            # -----------------------------------------------------
            # Verification rejected:
            # Bell + realtime Bell + email.
            # No inbox/envelope message.
            # -----------------------------------------------------
            notification = Notification.objects.create(
                user=verification_request.user,
                type="identity_verification_rejected",
                target_type="identity_verification",
                target_id=verification_request.id,
                title="Identity verification needs attention",
                body=(
                    "We couldn't approve your identity verification. "
                    "Review the reason and submit a new verification request."
                ),
            )

            push_user_realtime_event(
                verification_request.user.id,
                "new_notification",
                {
                    "kind": "identity_verification_rejected",
                    "notification_id": notification.id,
                    "target_type": "identity_verification",
                    "target_id": verification_request.id,
                },
            )

            template_exists = (
                NotificationTemplate.objects.filter(
                    key="identity_verification.rejected",
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    is_active=True,
                ).exists()
            )

            if template_exists:
                OutboundNotification.objects.create(
                    user=verification_request.user,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="identity_verification.rejected",
                    scheduled_for=timezone.now(),
                    context={
                        "user_name": (
                            verification_request.user.first_name
                            or verification_request.user.username
                        ),
                        "rejection_reason": rejection_reason,

                        # Permanent frontend resubmission/status route.
                        "resubmit_url": build_absolute_url(
                            "/identity-verification",
                            force_login=True,
                        ),

                        # Existing support route.
                        "support_url": build_absolute_url(
                            "/contact",
                            force_login=False,
                        ),

                        "current_year": timezone.now().year,
                        "verification_request_id": verification_request.id,
                    },
                )



            return ok_response(
                message="Landlord verification request rejected.",
                data=AdminLandlordVerificationRequestSerializer(verification_request).data,
            )