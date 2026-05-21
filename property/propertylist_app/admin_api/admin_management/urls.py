from django.urls import path

from .views import (
    AdminUserTableView,
    CreateAdminUserView,
    DeleteAdminUserView,
    AdminRolePermissionsView,
)


urlpatterns = [
    path(
        "admins/",
        AdminUserTableView.as_view(),
        name="admin-management-admins",
    ),
    
    
    path(
    "admins/create/",
    CreateAdminUserView.as_view(),
    name="admin-management-create-admin",
    ),
    
    path(
    "admins/<int:admin_user_id>/delete/",
    DeleteAdminUserView.as_view(),
    name="admin-management-delete-admin",
    ),
    
    
    path(
    "permissions/",
    AdminRolePermissionsView.as_view(),
    name="admin-management-permissions",
    ),
]