from datetime import timedelta

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from propertylist_app.api.serializers import CreateViewingBookingSerializer
from propertylist_app.models import AvailabilitySlot, Booking


VIEWING_DURATION = timedelta(minutes=30)


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
    },
)
class CreateViewingBookingView(APIView):
    """Create a lifecycle-safe viewing through the legacy viewing endpoint."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateViewingBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slot_id = serializer.validated_data.get("slot_id")
        room_id = serializer.validated_data.get("room_id")
        start = serializer.validated_data.get("start")

        if slot_id:
            slot = AvailabilitySlot.objects.get(id=slot_id)

            booking = Booking.objects.create(
                user=request.user,
                room=slot.room,
                start=slot.start,
                end=slot.end,
                status=Booking.STATUS_ACTIVE,
            )
        else:
            if not room_id or not start:
                raise ValidationError(
                    {"detail": "room_id and start are required when slot_id is not provided."}
                )

            booking = Booking.objects.create(
                user=request.user,
                room_id=room_id,
                start=start,
                end=start + VIEWING_DURATION,
                status=Booking.STATUS_ACTIVE,
            )

        return Response(
            {
                "ok": True,
                "message": "Viewing booked successfully",
                "data": {
                    "room_id": booking.room_id,
                    "start": booking.start,
                    "status": booking.status,
                },
            }
        )
