from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import (
    AdminUserTableResponseSerializer,
    CreateAdminRequestSerializer,
    CreateAdminResponseSerializer,
    DeleteAdminResponseSerializer,
    AdminRolePermissionsResponseSerializer,
    
    )
    
    
from .services import (
    get_admin_users_table_data,
    create_admin_user,
    delete_admin_user,
    get_admin_permissions_data,
)


class AdminUserTableView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminUserTableResponseSerializer,
    )
    def get(self, request):
        data = get_admin_users_table_data()

        return Response(
            {
                "ok": True,
                "message": "Admin users fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )
        
        
class CreateAdminUserView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=CreateAdminRequestSerializer,
        responses=CreateAdminResponseSerializer,
    )
    def post(self, request):
        serializer = CreateAdminRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = create_admin_user(serializer.validated_data)
        except ValidationError as exc:
            raise ValidationError({"detail": str(exc)})

        return Response(
            {
                "ok": True,
                "message": "Admin user created successfully",
                "data": data,
            },
            status=status.HTTP_201_CREATED,
        )        
        
        
class DeleteAdminUserView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=DeleteAdminResponseSerializer,
    )
    def delete(self, request, admin_user_id):
        try:
            data = delete_admin_user(admin_user_id)
        except ValidationError as exc:
            raise ValidationError({"detail": str(exc)})

        return Response(
            {
                "ok": True,
                "message": "Admin user removed successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )    
        
                
class AdminRolePermissionsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminRolePermissionsResponseSerializer,
    )
    def get(self, request):
        data = get_admin_permissions_data()

        return Response(
            {
                "ok": True,
                "message": "Admin role permissions fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )            
        