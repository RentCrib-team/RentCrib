from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import (
    IdentityVerificationRequest,
    Notification,
)
from propertylist_app.api.serializers import IdentityVerificationRequestSerializer
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.views.common import ok_response
from django.utils import timezone

from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
)

from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event



class MyIdentityVerificationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="api_v1_users_me_identity_verification_retrieve",
        responses={
            200: inline_serializer(
                name="MyIdentityVerificationGetResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": IdentityVerificationRequestSerializer(
                        required=False,
                        allow_null=True,
                    ),
                },
            ),
            401: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Authentication required.",
            ),
        },
        description=(
            "Return the authenticated user's latest identity verification "
            "request. The data field is null when no request exists."
        ),
    )
    def get(self, request):
        latest = (
            IdentityVerificationRequest.objects
            .filter(user=request.user)
            .order_by("-created_at")
            .first()
        )

        if not latest:
            return ok_response(
                message="No identity verification request found.",
                data=None,
            )

        return ok_response(
            message="Identity verification retrieved.",
            data=IdentityVerificationRequestSerializer(latest).data,
        )

    @extend_schema(
        operation_id="api_v1_users_me_identity_verification_create",
        request=IdentityVerificationRequestSerializer,
        responses={
            200: inline_serializer(
                name="MyIdentityVerificationPendingResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": IdentityVerificationRequestSerializer(),
                },
            ),
            201: inline_serializer(
                name="MyIdentityVerificationCreateResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": IdentityVerificationRequestSerializer(),
                },
            ),
            400: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Invalid identity verification submission.",
            ),
            401: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Authentication required.",
            ),
        },
        description=(
            "Submit an identity verification request for the authenticated "
            "user. If a pending request already exists, that request is returned."
        ),
    )
    def post(self, request):
        existing = (
            IdentityVerificationRequest.objects
            .filter(
                user=request.user,
                status="pending",
            )
            .first()
        )

        if existing:
            return ok_response(
                message="Identity verification already pending.",
                data=IdentityVerificationRequestSerializer(existing).data,
            )

        serializer = IdentityVerificationRequestSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        obj = serializer.save(
            user=request.user,
        )
        
        
        # ---------------------------------------------------------
        # Identity verification received
        # Account notification only:
        # Bell + realtime Bell + email.
        # No inbox/envelope message.
        # ---------------------------------------------------------

        notification = Notification.objects.create(
            user=request.user,
            type="identity_verification_received",
            target_type="identity_verification",
            target_id=obj.id,
            title="Identity verification received",
            body=(
                "We've received your identity verification "
                "and it is now waiting for review."
            ),
        )

        push_user_realtime_event(
            request.user.id,
            "new_notification",
            {
                "kind": "identity_verification_received",
                "notification_id": notification.id,
                "target_type": "identity_verification",
                "target_id": obj.id,
            },
        )

        template_exists = (
            NotificationTemplate.objects.filter(
                key="identity_verification.received",
                channel=NotificationTemplate.CHANNEL_EMAIL,
                is_active=True,
            ).exists()
        )

        if template_exists:
            OutboundNotification.objects.create(
                user=request.user,
                channel=NotificationTemplate.CHANNEL_EMAIL,
                template_key="identity_verification.received",
                scheduled_for=timezone.now(),
                context={
                    "user_name": (
                        request.user.first_name
                        or request.user.username
                    ),

                    # Permanent frontend verification route.
                    "dashboard_url": build_absolute_url(
                        "/identity-verification",
                        force_login=True,
                    ),

                    # Existing frontend contact/support route.
                    "support_url": build_absolute_url(
                        "/contact",
                        force_login=False,
                    ),

                    "current_year": timezone.now().year,
                    "verification_request_id": obj.id,
                },
            )
        
        
        

        return ok_response(
            message="Identity verification submitted.",
            data=IdentityVerificationRequestSerializer(obj).data,
            status_code=status.HTTP_201_CREATED,
        )