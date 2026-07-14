from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import DashboardOverviewResponseSerializer
from .services import get_dashboard_overview_data


class DashboardOverviewView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=DashboardOverviewResponseSerializer,
    )
    def get(self, request):
        data = get_dashboard_overview_data()

        return Response(
            {
                "ok": True,
                "message": "Admin dashboard overview fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )