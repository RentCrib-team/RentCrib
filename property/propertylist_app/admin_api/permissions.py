from rest_framework.permissions import BasePermission

from propertylist_app.api.permissions import ADMIN_ROLES, user_has_any_admin_role


class IsAdminUser(BasePermission):
    """
    Allows access only to approved admin dashboard users.
    """

    ALLOWED_ADMIN_ROLES = ADMIN_ROLES

    def has_permission(self, request, view):
        return user_has_any_admin_role(request.user)