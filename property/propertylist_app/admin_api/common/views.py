from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import (
    AdminNotificationDropdownResponseSerializer,
    AdminProfileDropdownResponseSerializer,
)
from .services import (
    get_notification_dropdown_data,
    get_profile_dropdown_data,
)


class AdminNotificationDropdownView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminNotificationDropdownResponseSerializer,
    )
    def get(self, request):
        data = get_notification_dropdown_data()

        return Response(
            {
                "ok": True,
                "message": "Admin notification dropdown fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )
        
        
class AdminProfileDropdownView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminProfileDropdownResponseSerializer,
    )
    def get(self, request):
        data = get_profile_dropdown_data(request.user)

        return Response(
            {
                "ok": True,
                "message": "Admin profile dropdown fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )        