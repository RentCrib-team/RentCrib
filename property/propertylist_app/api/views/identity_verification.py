from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import IdentityVerificationRequest
from propertylist_app.api.serializers import IdentityVerificationRequestSerializer
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.views.common import ok_response


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

        return ok_response(
            message="Identity verification submitted.",
            data=IdentityVerificationRequestSerializer(obj).data,
            status_code=status.HTTP_201_CREATED,
        )