from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import (
    ListingGrowthResponseSerializer,
    BookingTrendsResponseSerializer,
    PaymentStatusMixResponseSerializer,
    ModerationBacklogTrendsResponseSerializer,
)

from .services import (
    get_listing_growth_chart_data,
    get_booking_trends_chart_data,
    get_payment_status_mix_chart_data,
    get_moderation_backlog_trends_chart_data,
)


class ListingGrowthAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=ListingGrowthResponseSerializer,
    )
    def get(self, request):
        data = get_listing_growth_chart_data()

        return Response(
            {
                "ok": True,
                "message": "Listing growth analytics fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )



class BookingTrendsAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=BookingTrendsResponseSerializer,
    )
    def get(self, request):
        data = get_booking_trends_chart_data()

        return Response(
            {
                "ok": True,
                "message": "Booking trends analytics fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )        
        
        
class PaymentStatusMixAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=PaymentStatusMixResponseSerializer,
    )
    def get(self, request):
        data = get_payment_status_mix_chart_data()

        return Response(
            {
                "ok": True,
                "message": "Payment status mix analytics fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )        
        
        
class ModerationBacklogTrendsAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=ModerationBacklogTrendsResponseSerializer,
    )
    def get(self, request):
        data = get_moderation_backlog_trends_chart_data()

        return Response(
            {
                "ok": True,
                "message": "Moderation backlog trends analytics fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )        