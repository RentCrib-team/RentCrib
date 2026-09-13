from rest_framework.permissions import BasePermission

from propertylist_app.api.permissions import get_user_admin_role


class IsLocationAdmin(BasePermission):
    """Allow only Super Admin and Operations Admin to manage cities."""

    message = "You do not have permission to manage locations."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        return get_user_admin_role(user) in {"super_admin", "ops_admin"}
