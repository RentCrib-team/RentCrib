from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status

from propertylist_app.api.views.common import ok_response

from .serializers import (
    AdminBookingOverviewResponseSerializer,
    AdminBookingDetailResponseSerializer,
    AdminBookingActionRequestSerializer,
    AdminBookingActionResponseSerializer,
)

from .services import (
    get_admin_booking_overview_data,
    get_admin_booking_detail_data,
    update_admin_booking_action,
)


class AdminBookingOverviewView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminBookingOverviewResponseSerializer,
    )
    def get(self, request):
        data = get_admin_booking_overview_data(request.query_params)

        return ok_response(
            data=data,
            message="Admin booking overview fetched successfully.",
        )



class AdminBookingDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminBookingDetailResponseSerializer,
    )
    def get(self, request, booking_id):
        data = get_admin_booking_detail_data(booking_id)

        return ok_response(
            data=data,
            message="Admin booking detail fetched successfully.",
            status_code=status.HTTP_200_OK,
        )




class AdminBookingActionView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=AdminBookingActionRequestSerializer,
        responses=AdminBookingActionResponseSerializer,
    )
    def post(self, request, booking_id):
        serializer = AdminBookingActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = update_admin_booking_action(
            booking_id=booking_id,
            action=serializer.validated_data["action"],
        )

        return ok_response(
            data=result["booking"],
            message=result["message"],
            status_code=status.HTTP_200_OK,
        )