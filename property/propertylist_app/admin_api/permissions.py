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

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        profile = getattr(user, "profile", None)
        admin_role = getattr(profile, "admin_role", "") if profile else ""

        return admin_role in self.ALLOWED_ADMIN_ROLES