from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import ListingGrowthResponseSerializer
from .services import get_listing_growth_chart_data


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