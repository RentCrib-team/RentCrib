from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    """
    Allows access only to approved admin dashboard users.
    """

    ALLOWED_ADMIN_ROLES = {
        "super_admin",
        "ops_admin",
        "moderator",
        "finance_admin",
        "support_admin",
    }

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and getattr(user, "admin_role", "") in self.ALLOWED_ADMIN_ROLES
        )