from datetime import datetime, timedelta

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import Tenancy, Review
from propertylist_app.tasks import task_send_tenancy_notification
from propertylist_app.services.tenancy_dates import (
    compute_end_date,
    compute_review_window,
)
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.serializers import (
    TenancyDetailSerializer,
    TenancyRespondSerializer,
    TenancyProposalSerializer,
    StillLivingConfirmResponseSerializer,
    TenancyExtensionCreateSerializer,
    TenancyExtensionRespondSerializer,
    TenancyExtensionHistoryItemSerializer,
    TenancyExtensionResponseSerializer,
    DetailResponseSerializer,
)
from .common import ok_response


def _get_model(app_label: str, model_name: str):
    return apps.get_model(app_label, model_name)





class TenancyStillLivingConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: standard_response_serializer(
                "TenancyStillLivingConfirmResponse",
                StillLivingConfirmResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, tenancy_id: int, *args, **kwargs):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")

        t = Tenancy.objects.select_related("landlord", "tenant", "room").filter(id=tenancy_id).first()
        if not t:
            return Response(
                {
                    "ok": False,
                    "message": "Not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        if user.id not in (t.landlord_id, t.tenant_id):
            return Response(
                {
                    "ok": False,
                    "message": "Forbidden.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        now = timezone.now()

        active_status = getattr(Tenancy, "STATUS_ACTIVE", "active")
        if getattr(t, "status", None) != active_status:
            return Response(
                {
                    "ok": False,
                    "message": "Still-living confirmation is only allowed for active tenancies.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        check_at = getattr(t, "still_living_check_at", None)
        if check_at and now < check_at:
            return Response(
                {
                    "ok": False,
                    "message": "Still-living confirmation is not due yet.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated_fields = []

        if user.id == t.tenant_id and getattr(t, "still_living_tenant_confirmed_at", None) is None:
            t.still_living_tenant_confirmed_at = now
            updated_fields.append("still_living_tenant_confirmed_at")

        if user.id == t.landlord_id and getattr(t, "still_living_landlord_confirmed_at", None) is None:
            t.still_living_landlord_confirmed_at = now
            updated_fields.append("still_living_landlord_confirmed_at")

        landlord_done = bool(getattr(t, "still_living_landlord_confirmed_at", None))
        tenant_done = bool(getattr(t, "still_living_tenant_confirmed_at", None))

        if landlord_done and tenant_done and getattr(t, "still_living_confirmed_at", None) is None:
            t.still_living_confirmed_at = now
            updated_fields.append("still_living_confirmed_at")

        if updated_fields:
            t.save(update_fields=updated_fields)

        return ok_response(
            {
                "tenancy_id": t.id,
                "tenant_confirmed": bool(getattr(t, "still_living_tenant_confirmed_at", None)),
                "landlord_confirmed": bool(getattr(t, "still_living_landlord_confirmed_at", None)),
                "confirmed_at": getattr(t, "still_living_confirmed_at", None),
            },
            message="Still-living confirmation recorded successfully.",
            status_code=status.HTTP_200_OK,
        )
        
        



class TenancyExtensionCreateView(APIView):
    permission_classes = [IsAuthenticated]
    
    
    @extend_schema(
        responses={
            200: inline_serializer(
                name="TenancyExtensionHistoryOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "data": TenancyExtensionHistoryItemSerializer(
                        many=True,
                    ),
                },
            ),
            401: OpenApiResponse(
                description="Authentication required.",
            ),
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description=(
            "Return the complete renewal history for a tenancy. "
            "Only the tenancy landlord or tenant may access it. "
            "Results are ordered from oldest to newest."
        ),
    )
    def get(self, request, tenancy_id: int):
        Tenancy = _get_model(
            "propertylist_app",
            "Tenancy",
        )
        TenancyExtension = _get_model(
            "propertylist_app",
            "TenancyExtension",
        )

        tenancy = (
            Tenancy.objects
            .select_related(
                "landlord",
                "tenant",
            )
            .filter(
                id=tenancy_id,
            )
            .first()
        )

        if not tenancy:
            raise NotFound(
                "Tenancy not found."
            )

        user = request.user

        if user.id not in {
            tenancy.landlord_id,
            tenancy.tenant_id,
        }:
            raise PermissionDenied(
                "Forbidden."
            )

        extensions = (
            TenancyExtension.objects
            .select_related(
                "proposed_by",
            )
            .filter(
                tenancy_id=tenancy.id,
            )
            .order_by(
                "created_at",
                "id",
            )
        )

        history = []

        for extension in extensions:
            proposer = extension.proposed_by

            proposer_name = ""

            if proposer:
                proposer_name = (
                    proposer.get_full_name()
                    or proposer.username
                    or proposer.first_name
                    or ""
                )

            proposer_role = (
                "landlord"
                if extension.proposed_by_id
                == tenancy.landlord_id
                else "tenant"
            )

            history.append(
                {
                    "id": extension.id,
                    "tenancy_id": extension.tenancy_id,
                    "proposed_by_user_id": (
                        extension.proposed_by_id
                    ),
                    "proposed_by_name": proposer_name,
                    "proposed_by_role": proposer_role,
                    "proposed_start_date": (
                        extension.proposed_start_date
                    ),
                    "proposed_duration_months": (
                        extension.proposed_duration_months
                    ),
                    "status": extension.status,
                    "responded_at": (
                        extension.responded_at
                    ),
                    "created_at": extension.created_at,
                }
            )

        data = TenancyExtensionHistoryItemSerializer(
            history,
            many=True,
        ).data

        return ok_response(
            data,
            message=(
                "Tenancy renewal history retrieved "
                "successfully."
            ),
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
        request=TenancyExtensionCreateSerializer,
        responses={
            201: inline_serializer(
                name="TenancyExtensionCreateOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyExtensionResponseSerializer(),
                },
            ),
            400: DetailResponseSerializer,
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description="Create a tenancy extension proposal.",
    )
    def post(self, request, tenancy_id: int):
        Tenancy = _get_model("propertylist_app", "Tenancy")
        TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

        tenancy = Tenancy.objects.select_related("landlord", "tenant").filter(id=tenancy_id).first()
        if not tenancy:
            raise NotFound("Tenancy not found.")

        user = request.user
        if user.id not in {tenancy.landlord_id, tenancy.tenant_id}:
            raise PermissionDenied("Forbidden.")

        # Disallow if ended
        # Cancelled tenancies can never be renewed.
        cancelled_statuses = {
            getattr(Tenancy, "STATUS_CANCELLED", "cancelled"),
            getattr(Tenancy, "STATUS_CANCELED", "canceled"),
        }

        if getattr(tenancy, "status", None) in cancelled_statuses:
            raise ValidationError({
                "detail": "A cancelled tenancy cannot be updated."
            })

        now = timezone.now()

        # TEMPORARY QA RULE:
        # Timer 2 marks the start of the tenancy-update window.
        # The window remains open until the QA review stage begins.
        #
        # PRODUCTION:
        # Tenancy information can be updated/renewed from
        # 7 days before the real tenancy end date until the end date.
        #
        # Once the tenancy has genuinely ended, renewal is no longer
        # allowed and the room becomes available for reletting.
        update_window_start = tenancy.still_living_check_at
        update_window_end = tenancy.review_open_at

        if not update_window_start or not update_window_end:
            raise ValidationError({
                "detail": (
                    "Tenancy update window is not available yet."
                )
            })

        if now < update_window_start:
            raise ValidationError({
                "detail": (
                    "You can update this tenancy information "
                    "within the allowed update period."
                )
            })

        if now >= update_window_end:
            raise ValidationError({
                "detail": (
                    "The time allowed to update this tenancy "
                    "has expired."
                )
            })

        ser = TenancyExtensionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Only one open proposal at a time
        open_exists = TenancyExtension.objects.filter(
            tenancy=tenancy,
            status=TenancyExtension.STATUS_PROPOSED,
        ).exists()
        if open_exists:
            raise ValidationError({"detail": "An extension proposal is already open."})

        ext = TenancyExtension.objects.create(
            tenancy=tenancy,
            proposed_by=user,
            proposed_start_date=ser.validated_data[
                "proposed_start_date"
            ],
            proposed_duration_months=ser.validated_data[
                "proposed_duration_months"
            ],
            status=TenancyExtension.STATUS_PROPOSED,
        )
        

        payload = {
            "id": ext.id,
            "tenancy_id": ext.tenancy_id,
            "proposed_by_user_id": ext.proposed_by_id,
            "proposed_start_date": ext.proposed_start_date,
            "proposed_duration_months": (
                ext.proposed_duration_months
            ),
            "status": ext.status,
            "responded_at": ext.responded_at,
            "created_at": ext.created_at,
        }

        return ok_response(
            TenancyExtensionResponseSerializer(payload).data,
            message="Tenancy extension proposal created successfully.",
            status_code=status.HTTP_201_CREATED,
        )   
        
        
        
class TenancyExtensionRespondView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TenancyExtensionRespondSerializer,
        responses={
            200: standard_response_serializer(
                "TenancyExtensionRespondResponse",
                TenancyExtensionResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, tenancy_id: int, extension_id: int):
        Tenancy = _get_model("propertylist_app", "Tenancy")
        TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

        tenancy = Tenancy.objects.select_related("landlord", "tenant").filter(id=tenancy_id).first()
        if not tenancy:
            raise NotFound("Tenancy not found.")

        ext = TenancyExtension.objects.select_related("tenancy").filter(
            id=extension_id,
            tenancy_id=tenancy_id,
        ).first()
        if not ext:
            raise NotFound("Extension not found.")

        user = request.user
        if user.id not in {tenancy.landlord_id, tenancy.tenant_id}:
            raise PermissionDenied("Forbidden.")

        # Only counterparty can respond
        if user.id == ext.proposed_by_id:
            raise PermissionDenied("Proposer cannot respond.")

        if ext.status != TenancyExtension.STATUS_PROPOSED:
            raise ValidationError({
                "detail": "Extension is not open."
            })

        now = timezone.now()

        # ---------------------------------------------------------
        # TENANCY UPDATE WINDOW GUARD
        # ---------------------------------------------------------
        # A renewal proposal may only be accepted/rejected while the
        # tenancy update window is still open.
        #
        # TEMPORARY QA RULE:
        # still_living_check_at -> review_open_at = 10-minute window.
        #
        # Once review_open_at is reached, the tenancy lifecycle has
        # moved into the review phase and no tenancy mutation may occur.
        update_window_start = tenancy.still_living_check_at
        update_window_end = tenancy.review_open_at

        if tenancy.status == Tenancy.STATUS_ENDED:
            raise ValidationError({
                "detail": (
                    "This tenancy has ended. "
                    "The renewal can no longer be changed."
                )
            })

        if not update_window_start or not update_window_end:
            raise ValidationError({
                "detail": (
                    "Tenancy update window is not available."
                )
            })

        if now < update_window_start:
            raise ValidationError({
                "detail": (
                    "The tenancy update period has not started yet."
                )
            })

        if now >= update_window_end:
            raise ValidationError({
                "detail": (
                    "The time allowed to respond to this renewal "
                    "has expired."
                )
            })

        ser = TenancyExtensionRespondSerializer(
            data=request.data,
        )
        ser.is_valid(raise_exception=True)

        action = ser.validated_data["action"]

        if action == "reject":
            ext.status = TenancyExtension.STATUS_REJECTED
            ext.responded_at = now
            ext.save(update_fields=["status", "responded_at"])

        if action == "accept":
            ext.status = TenancyExtension.STATUS_ACCEPTED
            ext.responded_at = now
            ext.save(
                update_fields=[
                    "status",
                    "responded_at",
                ]
            )

            # The accepted extension becomes the tenancy's new
            # current rental period.
            tenancy.move_in_date = ext.proposed_start_date
            tenancy.duration_months = (
                ext.proposed_duration_months
            )

            # Recalculate all lifecycle dates from the accepted
            # renewal start date and renewal duration.
            (
                review_open_at,
                review_deadline_at,
                _production_still_living_check_at,
            ) = compute_review_window(
                tenancy.move_in_date,
                tenancy.duration_months,
            )

            tenancy.review_open_at = review_open_at
            tenancy.review_deadline_at = review_deadline_at

            # TEMPORARY QA RULE:
            # After a renewal is accepted, Timer 2 becomes due
            # 10 minutes later so the renewed-tenancy ending
            # reminder can be tested immediately.
            #
            # PRODUCTION:
            # Replace this with the value returned by
            # compute_review_window(), which schedules the reminder
            # seven days before the renewed tenancy end date.
            tenancy.still_living_check_at = (
                now + timedelta(minutes=10)
            )

            # Clear the previous ending-reminder state so the new
            # rental period gets its own future reminder cycle.
            tenancy.still_living_confirmed_at = None
            tenancy.still_living_landlord_confirmed_at = None
            tenancy.still_living_tenant_confirmed_at = None

            tenancy.status = (
                Tenancy.STATUS_ACTIVE
                if tenancy.move_in_date
                <= timezone.localdate()
                else Tenancy.STATUS_CONFIRMED
            )

            tenancy.save(
                update_fields=[
                    "move_in_date",
                    "duration_months",
                    "review_open_at",
                    "review_deadline_at",
                    "still_living_check_at",
                    "still_living_confirmed_at",
                    "still_living_landlord_confirmed_at",
                    "still_living_tenant_confirmed_at",
                    "status",
                    "updated_at",
                ]
            )

            # The room remains unavailable throughout the renewed
            # tenancy relationship.
            room = tenancy.room
            if room.is_available:
                room.is_available = False
                room.save(
                    update_fields=[
                        "is_available",
                        "updated_at",
                    ]
                )
        payload = {
            "id": ext.id,
            "tenancy_id": ext.tenancy_id,
            "proposed_by_user_id": ext.proposed_by_id,
            "proposed_start_date": ext.proposed_start_date,
            "proposed_duration_months": (
                ext.proposed_duration_months
            ),
            "status": ext.status,
            "responded_at": ext.responded_at,
            "created_at": ext.created_at,
        }

        return ok_response(
            TenancyExtensionResponseSerializer(payload).data,
            message="Tenancy extension response recorded successfully.",
            status_code=status.HTTP_200_OK,
        )




class TenancyProposeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=TenancyProposalSerializer,
        responses={
            201: inline_serializer(
                name="TenancyProposeOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyDetailSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Create a tenancy proposal.",
    )
    def post(self, request):
        serializer = TenancyProposalSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        tenancy = serializer.save()

        # Notify the other party (inbox + email via your existing notification system)
        from propertylist_app.tasks import task_send_tenancy_notification
        task_send_tenancy_notification.delay(tenancy.id, "proposed")

        return ok_response(
            TenancyDetailSerializer(
                tenancy,
                context={"request": request},
            ).data,
            message="Tenancy proposal created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    
    
    
class TenancyRespondView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=TenancyRespondSerializer,
        responses={
            200: inline_serializer(
                name="TenancyRespondOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyDetailSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            404: DetailResponseSerializer,
        },
        description="Respond to a tenancy proposal and return the updated tenancy.",
    )
    def post(self, request, tenancy_id):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")

        tenancy = (
            Tenancy.objects.select_related(
                "room",
                "landlord",
                "tenant",
                "tenant__profile",
            )
            .filter(id=tenancy_id)
            .first()
        )
        if not tenancy:
            raise NotFound("Tenancy not found.")
        serializer = TenancyRespondSerializer(
            data=request.data,
            context={"request": request, "tenancy": tenancy},
        )
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        tenancy = serializer.save()

        from propertylist_app.tasks import task_send_tenancy_notification

        if action == "propose_changes":
            task_send_tenancy_notification.delay(tenancy.id, "updated")
            response_message = (
                "Tenancy information corrected successfully. "
                "The updated details have been sent to both parties."
            )
        elif action == "cancel":
            task_send_tenancy_notification.delay(
                tenancy.id,
                "rejected_unverified",
            )
            response_message = (
                "The tenant-created tenancy claim was rejected successfully."
            )
        else:
            task_send_tenancy_notification.delay(tenancy.id, "confirmed")
            response_message = "Tenancy confirmed successfully."

        return ok_response(
            TenancyDetailSerializer(
                tenancy,
                context={"request": request},
            ).data,
            message=response_message,
            status_code=status.HTTP_200_OK,
        )               
        


class TenancyDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="TenancyDetailOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "data": TenancyDetailSerializer(),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            404: DetailResponseSerializer,
        },
        description=(
            "Return one tenancy belonging to the authenticated landlord "
            "or tenant."
        ),
    )
    def get(self, request, tenancy_id):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")

        tenancy = (
            Tenancy.objects.select_related(
                "room",
                "landlord",
                "tenant",
                "tenant__profile",
            )
            .filter(
                Q(landlord=request.user) | Q(tenant=request.user),
                id=tenancy_id,
            )
            .first()
        )

        if not tenancy:
            raise NotFound("Tenancy not found.")

        return ok_response(
            TenancyDetailSerializer(
                tenancy,
                context={"request": request},
            ).data,
            message="Tenancy retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )        
        
        
        

class MyTenanciesView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TenancyDetailSerializer

    def get_queryset(self):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")
        if getattr(self, "swagger_fake_view", False):
            return Tenancy.objects.none()
        user = self.request.user
        return (Tenancy.objects.select_related(
                "room",
                "landlord",
                "tenant",
                "tenant__profile",
            )
            .filter(Q(tenant=user) | Q(landlord=user))
            .order_by("-created_at")
        )



class TenancyStillLivingConfirmResponseSerializer(serializers.Serializer):
    tenancy_id = serializers.IntegerField()
    tenant_confirmed = serializers.BooleanField()
    landlord_confirmed = serializers.BooleanField()
    confirmed_at = serializers.DateTimeField(required=False, allow_null=True)
          
