import logging

from datetime import datetime
from django.db import transaction
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.throttling import UserRateThrottle
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from propertylist_app.services.message_threads import (
    get_or_create_canonical_thread,
)
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse,inline_serializer

from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.models import (
    Booking,
    IdempotencyKey,
    Room,
    AvailabilitySlot,
    UserProfile,
    Notification,
    Message,
    MessageThread,
)
from propertylist_app.validators import ensure_idempotency, validate_no_booking_conflict
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
    standard_paginated_response_serializer,
)
from propertylist_app.api.serializers import (
    BookingSerializer,
    BookingPreflightRequestSerializer,
    BookingPreflightResponseSerializer,
    BookingRescheduleSerializer,
    CreateViewingBookingSerializer,
)
from ..serializers import BookingCreateRequestSerializer, BookingResponseEnvelopeSerializer
from .common import ok_response, _pagination_meta, _wrap_response_success, error_response






logger = logging.getLogger(__name__)


class EmptyDataSerializer(serializers.Serializer):
    pass


@extend_schema(
    request=BookingPreflightRequestSerializer,
    responses={
        200: BookingPreflightResponseSerializer,
        400: OpenApiResponse(description="Missing/invalid fields or invalid datetime format."),
        401: OpenApiResponse(description="Authentication required."),
    },
    parameters=[
        OpenApiParameter(
            name="Idempotency-Key",
            type=str,
            location=OpenApiParameter.HEADER,
            required=False,
            description="Optional idempotency key to prevent duplicate booking creation.",
        ),
    ],
    description=(
        "Preflight validation for booking creation. Validates room, start/end datetimes, "
        "and checks for booking conflicts."
    ),
)
@transaction.atomic
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_booking(request):
    key = request.headers.get("Idempotency-Key")
    info = ensure_idempotency(
        user_id=request.user.id,
        key=key,
        action="create_booking",
        payload_bytes=request.body,
        idem_qs=IdempotencyKey.objects,
    )

    room_id = request.data.get("room")
    start_str = request.data.get("start")
    end_str = request.data.get("end")
    if not room_id or not start_str or not end_str:
        return error_response(
            message="room, start, and end are required.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="missing_required_fields",
        )

    room = get_object_or_404(Room, pk=room_id)
    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except Exception:
        return error_response(
            message="start and end must be ISO 8601 datetimes.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_datetime",
        )

    Booking.objects.select_for_update().filter(room=room)
    validate_no_booking_conflict(room, start_dt, end_dt, Booking.objects)

    IdempotencyKey.objects.create(
        user_id=request.user.id,
        key=key,
        action="create_booking",
        request_hash=info["request_hash"],
    )

    return ok_response(
        {"detail": "Validated. Ready to create booking."},
        status_code=status.HTTP_200_OK,
    )




# propertylist_app/api/views/bookings.py
@extend_schema(
    request=CreateViewingBookingSerializer,
    responses={
        200: {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "message": {"type": "string"},
                "data": {
                    "type": "object",
                    "properties": {
                        "room_id": {"type": "integer"},
                        "start": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            },
        }
    }
)
class CreateViewingBookingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        slot_id = request.data.get("slot_id")
        room_id = request.data.get("room_id")
        start = request.data.get("start")

        if slot_id:
            slot = AvailabilitySlot.objects.get(id=slot_id)

            booking = Booking.objects.create(
                user=request.user,
                room=slot.room,
                start=slot.start,
                end=slot.end,
                status="confirmed"
            )

        else:
            booking = Booking.objects.create(
                user=request.user,
                room_id=room_id,
                start=start,
                status="confirmed"
            )

        return Response({
            "ok": True,
            "message": "Viewing booked successfully",
            "data": {
                "room_id": booking.room_id,
                "start": booking.start,
                "status": booking.status
            }
        })






# --------------------
# Booking
# --------------------
class BookingListCreateView(generics.ListCreateAPIView):
    """GET my bookings / POST create (slot OR direct)."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination
    throttle_classes = [UserRateThrottle]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ["start", "end", "created_at", "id"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BookingCreateRequestSerializer
        return BookingSerializer

    @extend_schema(
        request=BookingCreateRequestSerializer,
        responses={
            201: standard_response_serializer(
                "BookingCreateResponse",
                BookingSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Create a booking using either a slot OR room/start/end.",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        booking = serializer.instance

        return ok_response(
            BookingSerializer(booking, context=self.get_serializer_context()).data,
            message="Booking created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        user = self.request.user
        qs = Booking.objects.filter(is_deleted=False)

        room_id = self.request.query_params.get("room")
        scope = self.request.query_params.get("scope")

        if not room_id:
            return qs.filter(user=user).order_by("-created_at")

        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        if scope == "viewers":
            if room.property_owner_id != user.id:
                return Booking.objects.none()
            return qs.filter(room=room).order_by("-created_at")

        return qs.filter(user=user, room=room).order_by("-created_at")

    def perform_create(self, serializer):
        slot_id = self.request.data.get("slot")
        if slot_id:
            slot = get_object_or_404(AvailabilitySlot, pk=slot_id)

            if getattr(slot.room, "is_deleted", False):
                raise ValidationError({"room": "Room is not available."})

            if slot.end <= timezone.now():
                raise ValidationError({"slot": "This slot is in the past."})

            with transaction.atomic():
                slot_locked = AvailabilitySlot.objects.select_for_update().get(pk=slot.pk)
                active = Booking.objects.filter(
                    slot=slot_locked,
                    canceled_at__isnull=True,
                    is_deleted=False,
                ).count()
                if active >= slot_locked.max_bookings:
                    raise ValidationError({"detail": "This slot is fully booked."})

                booking = serializer.save(
                    user=self.request.user,
                    room=slot_locked.room,
                    slot=slot_locked,
                    start=slot_locked.start,
                    end=slot_locked.end,
                )

            profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
            if getattr(profile, "notify_confirmations", True):
                notification = Notification.objects.create(
                    user=self.request.user,
                    type="confirmation",
                    target_type="booking",
                    target_id=booking.id,
                    title="Booking confirmed",
                    body="Your booking has been successfully created.",
                    audience=Notification.Audience.SEEKER,
                )

                push_user_realtime_event(
                    self.request.user.id,
                    "new_notification",
                    {
                        "kind": "booking_confirmation",
                        "notification_id": notification.id,
                        "target_type": "booking",
                        "target_id": booking.id,
                    },
                )
            return

        room_id = self.request.data.get("room")
        if not room_id:
            raise ValidationError({"room": "This field is required."})
        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        start = serializer.validated_data.get("start")
        end = serializer.validated_data.get("end")

        if not start or not end:
            raise ValidationError({"start": "start and end are required."})
        if start >= end:
            raise ValidationError({"end": "End must be after start."})

        with transaction.atomic():
            Booking.objects.select_for_update().filter(room=room, canceled_at__isnull=True)

            conflicts = (
                Booking.objects
                .filter(room=room, canceled_at__isnull=True, is_deleted=False)
                .filter(start__lt=end, end__gt=start)
                .exists()
            )
            if conflicts:
                raise ValidationError({"detail": "Selected dates clash with an existing booking."})

            booking = serializer.save(
                user=self.request.user,
                room=room,
            )

        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        if getattr(profile, "notify_confirmations", True):
                notification = Notification.objects.create(
                    user=self.request.user,
                    type="confirmation",
                    target_type="booking",
                    target_id=booking.id,
                    title="Booking confirmed",
                    body="Your booking has been successfully created.",
                    audience=Notification.Audience.SEEKER,
                )

                push_user_realtime_event(
                    self.request.user.id,
                    "new_notification",
                    {
                        "kind": "booking_confirmation",
                        "notification_id": notification.id,
                        "target_type": "booking",
                        "target_id": booking.id,
                    },
                )
    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedBookingListResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": BookingSerializer(many=True),
                    "meta": inline_serializer(
                        name="BookingListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(required=False, allow_null=True),
                            "previous": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                    "count": serializers.IntegerField(required=False, allow_null=True),
                    "next": serializers.CharField(required=False, allow_null=True),
                    "previous": serializers.CharField(required=False, allow_null=True),
                    "results": BookingSerializer(many=True, required=False),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of bookings to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of bookings to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="room",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter bookings by room id.",
            ),
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional scope. Use 'viewers' for landlord room viewers mode.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort by start, end, created_at, id, or their descending variants.",
            ),
        ],
        description="List bookings wrapped in ok_response. Supports limit/offset pagination, room filtering, scope filtering, and ordering.",
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            meta = _pagination_meta(self.paginator)

            return Response(
                {
                    "ok": True,
                    "message": None,
                    "data": serializer.data,
                    "meta": meta,
                    # compatibility keys for tests / standard pagination consumers
                    "count": meta.get("count"),
                    "next": meta.get("next"),
                    "previous": meta.get("previous"),
                    "results": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "ok": True,
                "message": None,
                "data": serializer.data,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )



class LandlordViewingsListView(generics.ListAPIView):
    """
    Return all viewing bookings for rooms owned by the authenticated landlord.
    """

    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination
    throttle_classes = [UserRateThrottle]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["start", "end", "created_at", "id"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()

        return (
            Booking.objects
            .filter(
                room__property_owner=self.request.user,
                is_deleted=False,
            )
            .select_related(
                "room",
                "user",
                "slot",
            )
            .order_by("-created_at")
        )

    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedLandlordViewingsListResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "data": BookingSerializer(many=True),
                    "meta": inline_serializer(
                        name="LandlordViewingsListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(
                                required=False,
                                allow_null=True,
                            ),
                            "previous": serializers.CharField(
                                required=False,
                                allow_null=True,
                            ),
                        },
                    ),
                    "count": serializers.IntegerField(
                        required=False,
                        allow_null=True,
                    ),
                    "next": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "previous": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "results": BookingSerializer(
                        many=True,
                        required=False,
                    ),
                },
            ),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of landlord viewings to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of landlord viewings to skip.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Sort by start, end, created_at, id, "
                    "or their descending variants."
                ),
            ),
        ],
        description=(
            "List all non-deleted viewing bookings across rooms owned by "
            "the authenticated landlord."
        ),
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        def serialize_with_effective_status(objects):
            serializer = self.get_serializer(objects, many=True)
            data = list(serializer.data)
            now = timezone.now()

            booking_by_id = {
                booking.id: booking
                for booking in objects
            }

            for row in data:
                booking = booking_by_id.get(row.get("id"))

                if not booking:
                    continue

                if row.get("status") == "cancelled":
                    continue

                if (
                    booking.start
                    and now >= booking.start + timedelta(minutes=10)
                ):
                    row["status"] = "completed"

            return data

        page = self.paginate_queryset(queryset)

        if page is not None:
            data = serialize_with_effective_status(page)
            meta = _pagination_meta(self.paginator)

            return Response(
                {
                    "ok": True,
                    "message": None,
                    "data": data,
                    "meta": meta,
                    "count": meta.get("count"),
                    "next": meta.get("next"),
                    "previous": meta.get("previous"),
                    "results": data,
                },
                status=status.HTTP_200_OK,
            )

        data = serialize_with_effective_status(queryset)

        return Response(
            {
                "ok": True,
                "message": None,
                "data": data,
                "results": data,
            },
            status=status.HTTP_200_OK,
        )
        
    
class BookingDetailView(generics.RetrieveAPIView):
    """GET /api/bookings/<id>/ â†’ see my booking"""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Booking.objects.filter(is_deleted=False)
        return Booking.objects.filter(user=self.request.user, is_deleted=False)

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "BookingDetailResponse",
                BookingSerializer,
            ),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Retrieve a booking owned by the authenticated user.",
    )
    def retrieve(self, request, *args, **kwargs):
        resp = super().retrieve(request, *args, **kwargs)
        return _wrap_response_success(resp)



class BookingRescheduleView(APIView):
    """
    PATCH /api/v1/bookings/{id}/reschedule/

    Landlord or seeker can change viewing date/time.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=BookingRescheduleSerializer,
        responses={
            200: standard_response_serializer(
                "BookingRescheduleResponse",
                BookingSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Reschedule a viewing. The landlord or seeker for the booking can reschedule.",
    )
    def patch(self, request, pk):

        booking = get_object_or_404(
            Booking.objects.filter(is_deleted=False),
            pk=pk,
        )

        landlord = booking.room.property_owner
        seeker = booking.user

        if request.user not in {landlord, seeker}:
            return error_response(
                message="Only the landlord or seeker for this viewing can reschedule it.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="not_booking_participant",
            )

        if booking.status != Booking.STATUS_ACTIVE:
            return error_response(
                message="Only active bookings can be rescheduled.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_not_active",
            )

        if booking.start <= timezone.now():
            return error_response(
                message="Cannot reschedule a viewing that has already started.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_started",
            )

        serializer = BookingRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_start = serializer.validated_data["start"]
        new_end = serializer.validated_data["end"]

        conflict = Booking.objects.filter(
            room=booking.room,
            is_deleted=False,
            canceled_at__isnull=True,
            start__lt=new_end,
            end__gt=new_start,
        ).exclude(id=booking.id).exists()

        if conflict:
            return error_response(
                message="Selected time conflicts with another viewing.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_conflict",
            )

        booking.start = new_start
        booking.end = new_end
        booking.save(update_fields=["start", "end"])


        # ---------------------------------------------------------
        # Notify the other party after a successful reschedule.
        #
        # Relationship action rule:
        # 1) shared RentCrib inbox/envelope message
        # 2) bell notification for the other party
        # 3) email for the other party
        # 4) realtime envelope update for both parties
        # 5) realtime bell update for the recipient
        # ---------------------------------------------------------

        from notifications.models import (
            NotificationTemplate,
            OutboundNotification,
        )

        recipient = (
            seeker
            if request.user == landlord
            else landlord
        )

        changed_by_name = (
            request.user.get_full_name().strip()
            or request.user.username
            or request.user.first_name
            or "The other party"
        )

        start_local = timezone.localtime(booking.start)
        end_local = timezone.localtime(booking.end)

        start_text = start_local.strftime(
            "%d %b %Y, %H:%M"
        )
        end_text = end_local.strftime(
            "%d %b %Y, %H:%M"
        )

        # ---------------------------------------------------------
        # 1. SHARED ENVELOPE / INBOX MESSAGE
        # ---------------------------------------------------------
        thread = get_or_create_canonical_thread(
            landlord=landlord,
            seeker=seeker,
            room=booking.room,
        )

        event_key = (
            f"booking:{booking.id}:"
            f"{booking.start.isoformat()}:"
            "rescheduled"
        )

        system_message = (
            Message.objects
            .filter(
                metadata__event_key=event_key
            )
            .first()
        )

        if system_message is None:
            system_message = Message.objects.create(
                thread=thread,
                sender=request.user,
                body=(
                    "Viewing rescheduled\n\n"
                    f"{changed_by_name} changed the viewing "
                    f"time for {booking.room.title}.\n\n"
                    f"New time: {start_text} - {end_text}"
                ),
                message_type=Message.TYPE_TEXT,
                metadata={
                    "system_event": True,
                    "event_type": "booking_rescheduled",
                    "event_key": event_key,
                    "booking_id": booking.id,
                    "room_id": booking.room_id,
                    "room": {"title": booking.room.title,},  
                    "changed_by_id": request.user.id,
                    "changed_by_name": changed_by_name,
                    "new_start": booking.start.isoformat(),
                    "new_end": booking.end.isoformat(),
                },
            )

            # The shared conversation changed for both parties.
            for user in (
                landlord,
                seeker,
            ):
                if not user:
                    continue

                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                        "sender_id": system_message.sender_id,
                    },
                )

        # ---------------------------------------------------------
        # 2. BELL NOTIFICATION
        # ---------------------------------------------------------
        recipient_profile, _ = (
            UserProfile.objects.get_or_create(
                user=recipient
            )
        )

        if getattr(
            recipient_profile,
            "notify_confirmations",
            True,
        ):
            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=recipient,
                    type="booking_rescheduled",
                    target_type="message",
                    target_id=system_message.id,
                    defaults={
                        "thread": thread,
                        "audience": (
                            Notification.Audience.SEEKER
                            if recipient == seeker
                            else Notification.Audience.LANDLORD
                        ),
                        "message": system_message,
                        "title": "Viewing rescheduled",
                        "body": (
                            f"{changed_by_name} changed the "
                            f"viewing time for "
                            f"{booking.room.title} to "
                            f"{start_text}."
                        ),
                    },
                )
            )

            if notification_created:
                push_user_realtime_event(
                    recipient.id,
                    "new_notification",
                    {
                        "kind": "booking_rescheduled",
                        "notification_id": notification.id,
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                    },
                )

            # -----------------------------------------------------
            # 3. EMAIL
            # -----------------------------------------------------
            template_exists = (
                NotificationTemplate.objects.filter(
                    key="booking.updated",
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    is_active=True,
                ).exists()
            )

            if template_exists:
                OutboundNotification.objects.create(
                    user=recipient,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.updated",
                    context={
                        "user": {
                            "first_name": recipient.first_name,
                        },
                        "changed_by": {
                            "name": changed_by_name,
                        },
                        "room": {
                            "title": booking.room.title,
                        },
                        "booking_id": booking.id,
                        "new_start": booking.start.isoformat(),
                        "new_end": booking.end.isoformat(),

                        # Mobile app deep link.
                        "deep_link": (
                            f"/app/bookings/{booking.id}"
                        ),

                        # Web/Vercel email action button.
                        "cta_url": build_absolute_url(
                            f"/messages?thread={thread.id}",
                            force_login=True,
                        ),
                    },
                )

        return ok_response(
            BookingSerializer(
                booking,
                context={"request": request}
            ).data,
            message="Viewing rescheduled successfully.",
            status_code=status.HTTP_200_OK,
        )




# ======================================================================
# 3) OPTIONAL BUT RECOMMENDED: make BookingCancelView ignore deleted bookings
# FILE: property/propertylist_app/api/views.py
# WHERE: inside BookingCancelView.post()
# REPLACE your first qs line with the 2 lines below
# ======================================================================





class BookingCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="BookingCancelResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="BookingCancelData",
                        fields={
                            "detail": serializers.CharField(),
                            "canceled_at": serializers.DateTimeField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Cancel a booking. Returns ok_response envelope.",
    )
    def post(self, request, pk):
        qs = Booking.objects.filter(is_deleted=False)

        if not request.user.is_staff:
            qs = qs.filter(
                Q(user=request.user) | Q(room__property_owner=request.user)
            )

        booking = get_object_or_404(qs, pk=pk)

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return error_response(
                message="Booking already cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_already_cancelled",
            )

        if booking.status == Booking.STATUS_SUSPENDED:
            return error_response(
                message="Suspended bookings cannot be cancelled.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_suspended",
            )

        if booking.start <= timezone.now():
            return error_response(
                message="Cannot cancel after booking has started.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_started",
            )

        booking.status = Booking.STATUS_CANCELLED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        landlord = booking.room.property_owner
        seeker = booking.user

        recipient = (
            seeker
            if request.user == landlord
            else landlord
        )

        cancelled_by_name = (
            request.user.get_full_name().strip()
            or request.user.username
            or request.user.first_name
            or "The other party"
        )

        # ---------------------------------------------------------
        # 1. SHARED RENTCRIB ENVELOPE / INBOX MESSAGE
        # ---------------------------------------------------------
        thread = get_or_create_canonical_thread(
            landlord=landlord,
            seeker=seeker,
            room=booking.room,
        )

        event_key = (
            f"booking:{booking.id}:cancelled"
        )

        system_message = (
            Message.objects
            .filter(
                metadata__event_key=event_key,
            )
            .first()
        )

        if system_message is None:
            system_message = Message.objects.create(
                thread=thread,
                sender=request.user,
                body=(
                    "Viewing cancelled\n\n"
                    f"{cancelled_by_name} cancelled the viewing "
                    f"for {booking.room.title}."
                ),
                message_type=Message.TYPE_TEXT,
                metadata={
                    "system_event": True,
                    "event_type": "booking_cancelled",
                    "event_key": event_key,
                    "booking_id": booking.id,
                    "room_id": booking.room_id,
                    "room": {   "title": booking.room.title,},
                    "cancelled_by_id": request.user.id,
                    "cancelled_by_name": cancelled_by_name,
                },
            )

            for user in (
                landlord,
                seeker,
            ):
                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                        "sender_id": system_message.sender_id,
                    },
                )

        # ---------------------------------------------------------
        # 2. RECIPIENT BELL
        # ---------------------------------------------------------
        recipient_profile, _ = (
            UserProfile.objects.get_or_create(
                user=recipient,
            )
        )

        if getattr(
            recipient_profile,
            "notify_confirmations",
            True,
        ):
            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=recipient,
                    type="booking_cancelled",
                    target_type="message",
                    target_id=system_message.id,
                    defaults={
                        "audience": (
                            Notification.Audience.SEEKER
                            if recipient == seeker
                            else Notification.Audience.LANDLORD
                        ),
                        "thread": thread,
                        "message": system_message,
                        "title": "Viewing cancelled",
                        "body": (
                            f"{cancelled_by_name} cancelled the "
                            f"viewing for {booking.room.title}."
                        ),
                    },
                )
            )

            if notification_created:
                push_user_realtime_event(
                    recipient.id,
                    "new_notification",
                    {
                        "kind": "booking_cancelled",
                        "notification_id": notification.id,
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                    },
                )
                
                
                
            # ---------------------------------------------------------
            # 3. RECIPIENT EMAIL
            # ---------------------------------------------------------
            if getattr(
                recipient_profile,
                "notify_confirmations",
                True,
            ):
                from notifications.models import (
                    NotificationTemplate,
                    OutboundNotification,
                )

                template_exists = (
                    NotificationTemplate.objects.filter(
                        key="booking.cancelled",
                        channel=NotificationTemplate.CHANNEL_EMAIL,
                        is_active=True,
                    ).exists()
                )

                if template_exists:
                    OutboundNotification.objects.create(
                        user=recipient,
                        channel=NotificationTemplate.CHANNEL_EMAIL,
                        template_key="booking.cancelled",
                        context={
                            "user": {
                                "first_name": recipient.first_name,
                            },
                            "cancelled_by_name": cancelled_by_name,
                            "room": {"title": booking.room.title,},
                            "booking_id": booking.id,

                            # Mobile app destination.
                            "deep_link": (
                                f"/app/threads/{thread.id}"
                            ),

                            # Web/Vercel action button.
                            "cta_url": build_absolute_url(
                                f"/messages?thread={thread.id}",
                                force_login=True,
                            ),
                        },
                    )
                
                
                
                    

        logger.info(
            "booking_cancel_success booking_id=%s user_id=%s status=%s",
            booking.id,
            request.user.id,
            booking.status,
        )

        return ok_response(
            {
                "detail": "Booking cancelled.",
                "canceled_at": booking.canceled_at,
            },
            status_code=status.HTTP_200_OK,
        )





class BookingSuspendView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="BookingSuspendResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="BookingSuspendData",
                        fields={
                            "id": serializers.IntegerField(),
                            "status": serializers.CharField(),
                            "canceled_at": serializers.DateTimeField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Suspend a booking. Returns ok_response envelope.",
    )
    def post(self, request, pk):
        booking = get_object_or_404(
            Booking.objects.filter(is_deleted=False).select_related("room"),
            pk=pk,
        )

        if (
            not request.user.is_staff
            and booking.user_id != request.user.id
            and booking.room.property_owner_id != request.user.id
        ):
            return error_response(
                message="You are not allowed to suspend this booking.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="permission_denied",
            )

        if booking.status == Booking.STATUS_SUSPENDED:
            return error_response(
                message="Booking already suspended.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_already_suspended",
            )

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return error_response(
                message="Cancelled bookings cannot be suspended.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_cancelled",
            )

        if booking.start <= timezone.now():
            return error_response(
                message="Cannot suspend after booking has started.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_started",
            )

        if booking.status != Booking.STATUS_ACTIVE:
            return error_response(
                    message="Only active bookings can be suspended.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="booking_not_active",
                )

        booking.status = Booking.STATUS_SUSPENDED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        landlord = booking.room.property_owner
        seeker = booking.user

        suspended_by_name = (
            request.user.get_full_name().strip()
            or request.user.username
            or request.user.first_name
            or "RentCrib"
        )

        # If landlord/seeker suspended it, notify the other party.
        # If staff suspended it, notify both booking participants.
        if request.user == landlord:
            notification_recipients = [seeker]

        elif request.user == seeker:
            notification_recipients = [landlord]

        else:
            notification_recipients = [
                user
                for user in (landlord, seeker)
                if user
            ]

        # ---------------------------------------------------------
        # 1. SHARED RENTCRIB ENVELOPE / INBOX MESSAGE
        # ---------------------------------------------------------
        thread = get_or_create_canonical_thread(
            landlord=landlord,
            seeker=seeker,
            room=booking.room,
        )

        event_key = (
            f"booking:{booking.id}:suspended"
        )

        system_message = (
            Message.objects
            .filter(
                metadata__event_key=event_key,
            )
            .first()
        )

        if system_message is None:
            # A system event still requires a real sender FK.
            # Use the acting participant where possible; otherwise
            # use the landlord for a staff-triggered suspension.
            message_sender = (
                request.user
                if request.user in {landlord, seeker}
                else landlord
            )

            system_message = Message.objects.create(
                thread=thread,
                sender=message_sender,
                body=(
                    "Viewing suspended\n\n"
                    f"The viewing for {booking.room.title} "
                    "has been suspended."
                ),
                message_type=Message.TYPE_TEXT,
                metadata={
                    "system_event": True,
                    "event_type": "booking_suspended",
                    "event_key": event_key,
                    "booking_id": booking.id,
                    "room_id": booking.room_id,
                    "room": {"title": booking.room.title,},
                    "suspended_by_id": request.user.id,
                    "suspended_by_name": suspended_by_name,
                },
            )

            # Both participants' inbox/envelope should update.
            for user in (
                landlord,
                seeker,
            ):
                if not user:
                    continue

                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                        "sender_id": system_message.sender_id,
                    },
                )

        # ---------------------------------------------------------
        # 2. BELL NOTIFICATION
        # ---------------------------------------------------------
        for recipient in notification_recipients:
            recipient_profile, _ = (
                UserProfile.objects.get_or_create(
                    user=recipient,
                )
            )

            if not getattr(
                recipient_profile,
                "notify_confirmations",
                True,
            ):
                continue

            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=recipient,
                    type="booking_suspended",
                    target_type="message",
                    target_id=system_message.id,
                    defaults={
                        "thread": thread,
                        "audience": (
                            Notification.Audience.LANDLORD
                            if recipient == landlord
                            else Notification.Audience.SEEKER
                        ),
                        "message": system_message,
                        "title": "Viewing suspended",
                        "body": (
                            f"The viewing for "
                            f"{booking.room.title} "
                            "has been suspended."
                        ),
                    },
                )
            )

            if notification_created:
                push_user_realtime_event(
                    recipient.id,
                    "new_notification",
                    {
                        "kind": "booking_suspended",
                        "notification_id": notification.id,
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                    },
                )
                
                
            # -----------------------------------------------------
            # 3. RECIPIENT EMAIL
            # -----------------------------------------------------
            from notifications.models import (
                NotificationTemplate,
                OutboundNotification,
            )

            template_exists = (
                NotificationTemplate.objects.filter(
                    key="booking.suspended",
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    is_active=True,
                ).exists()
            )

            if template_exists:
                OutboundNotification.objects.create(
                    user=recipient,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.suspended",
                    context={
                        "user": {
                            "first_name": recipient.first_name,
                        },
                        "room": {"title": booking.room.title,},
                        "booking_id": booking.id,
                        "suspended_by_name": suspended_by_name,

                        # Mobile app destination.
                        "deep_link": (
                            f"/app/threads/{thread.id}"
                        ),

                        # Web/Vercel action button.
                        "cta_url": build_absolute_url(
                            f"/messages?thread={thread.id}",
                            force_login=True,
                        ),
                    },
                )    
                
                
                

        logger.info(
            "booking_suspend_success booking_id=%s user_id=%s status=%s",
            booking.id,
            request.user.id,
            booking.status,
        )

        return ok_response(
            {
                "id": booking.id,
                "status": booking.status,
                "canceled_at": booking.canceled_at,
            },
            status_code=status.HTTP_200_OK,
        )

class BookingDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "BookingDeleteResponse",
                EmptyDataSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Delete a booking.",
    )
    def delete(self, request, pk, *args, **kwargs):
        qs = Booking.objects.filter(is_deleted=False)

        if not request.user.is_staff:
            qs = qs.filter(
                Q(user=request.user) | Q(room__property_owner=request.user)
            )

        booking = get_object_or_404(qs, pk=pk)

        now = timezone.now()

        if booking.status == Booking.STATUS_SUSPENDED:
            return error_response(
                message="Suspended bookings cannot be deleted.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_suspended",
            )

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return error_response(
                message="Cancelled bookings cannot be deleted.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_cancelled",
            )

        if booking.start and booking.start <= now:
            return error_response(
                message="Cannot delete a booking that has started.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="booking_started",
            )

        booking.is_deleted = True
        booking.deleted_at = now
        booking.save(update_fields=["is_deleted", "deleted_at"])

        landlord = booking.room.property_owner
        seeker = booking.user

        deleted_by_name = (
            request.user.get_full_name().strip()
            or request.user.username
            or request.user.first_name
            or "RentCrib"
        )

        # Landlord deletes -> notify seeker.
        # Seeker deletes -> notify landlord.
        # Staff deletes -> notify both parties.
        if request.user == landlord:
            notification_recipients = [seeker]

        elif request.user == seeker:
            notification_recipients = [landlord]

        else:
            notification_recipients = [
                user
                for user in (landlord, seeker)
                if user
            ]

        # ---------------------------------------------------------
        # 1. SHARED RENTCRIB ENVELOPE / INBOX MESSAGE
        # ---------------------------------------------------------
        thread = get_or_create_canonical_thread(
            landlord=landlord,
            seeker=seeker,
            room=booking.room,
        )

        event_key = (
            f"booking:{booking.id}:deleted"
        )

        system_message = (
            Message.objects
            .filter(
                metadata__event_key=event_key,
            )
            .first()
        )

        if system_message is None:
            message_sender = (
                request.user
                if request.user in {landlord, seeker}
                else landlord
            )

            system_message = Message.objects.create(
                thread=thread,
                sender=message_sender,
                body=(
                    "Viewing removed\n\n"
                    f"{deleted_by_name} removed the viewing "
                    f"for {booking.room.title}."
                ),
                message_type=Message.TYPE_TEXT,
                metadata={
                    "system_event": True,
                    "event_type": "booking_deleted",
                    "event_key": event_key,
                    "booking_id": booking.id,
                    "room_id": booking.room_id,
                    "room": {"title": booking.room.title,},
                    "deleted_by_id": request.user.id,
                    "deleted_by_name": deleted_by_name,
                },
            )

            for user in (
                landlord,
                seeker,
            ):
                if not user:
                    continue

                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                        "sender_id": system_message.sender_id,
                    },
                )

        # ---------------------------------------------------------
        # 2. BELL NOTIFICATION
        # ---------------------------------------------------------
        for recipient in notification_recipients:
            recipient_profile, _ = (
                UserProfile.objects.get_or_create(
                    user=recipient,
                )
            )

            if not getattr(
                recipient_profile,
                "notify_confirmations",
                True,
            ):
                continue

            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=recipient,
                    type="booking_deleted",
                    target_type="message",
                    target_id=system_message.id,
                    defaults={
                        "thread": thread,
                        "audience": (
                            Notification.Audience.LANDLORD
                            if recipient == landlord
                            else Notification.Audience.SEEKER
                        ),
                        "message": system_message,
                        "title": "Viewing removed",
                        "body": (
                            f"{deleted_by_name} removed the "
                            f"viewing for {booking.room.title}."
                        ),
                    },
                )
            )

            if notification_created:
                push_user_realtime_event(
                    recipient.id,
                    "new_notification",
                    {
                        "kind": "booking_deleted",
                        "notification_id": notification.id,
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                    },
                )
                
                
                
            from notifications.models import (
                NotificationTemplate,
                OutboundNotification,
            )

            template_exists = (
                NotificationTemplate.objects.filter(
                    key="booking.deleted",
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    is_active=True,
                ).exists()
            )

            if template_exists:
                OutboundNotification.objects.create(
                    user=recipient,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.deleted",
                    context={
                        "user": {
                            "first_name": recipient.first_name,
                        },
                        "deleted_by_name": deleted_by_name,
                        "room": {
                            "title": booking.room.title,
                        },
                        "booking_id": booking.id,

                        # Mobile app destination.
                        "deep_link": f"/app/threads/{thread.id}",

                        # Web/Vercel action button.
                        "cta_url": build_absolute_url(
                            f"/messages?thread={thread.id}",
                            force_login=True,
                        ),
                    },
                )
            
                

        logger.info(
            "booking_delete_success booking_id=%s user_id=%s is_deleted=%s",
            booking.id,
            request.user.id,
            booking.is_deleted,
        )

        return ok_response(
            {},
            message="Booking deleted successfully.",
            status_code=status.HTTP_200_OK,
        )





