from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .services import get_dashboard_overview_data


class DashboardOverviewView(APIView):
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