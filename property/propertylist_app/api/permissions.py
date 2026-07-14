from rest_framework import permissions

ADMIN_ROLES = {
    "super_admin",
    "ops_admin",
    "moderator",
    "finance_admin",
    "support_admin",
}


def get_user_admin_role(user) -> str:
    """
    Return the user's RentCrib admin role from their profile.
    Returns an empty string where the user has no admin role.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    profile = getattr(user, "profile", None)
    return getattr(profile, "admin_role", "") if profile else ""


def user_has_any_admin_role(user) -> bool:
    """
    True when the user is an approved RentCrib admin.
    Superusers are always treated as admins.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    return get_user_admin_role(user) in ADMIN_ROLES


def user_has_admin_role(user, allowed_roles) -> bool:
    """
    True when the user has one of the allowed RentCrib admin roles.
    Superusers are always allowed.
    Staff users are also allowed to preserve the existing endpoint contract.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    if getattr(user, "is_staff", False):
        return True

    return get_user_admin_role(user) in set(allowed_roles or [])

class IsOwner(permissions.BasePermission):
    """
    Strict ownership check (no read-only bypass).
    Useful for sensitive endpoints (delete, billing, etc.)
    """

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None) or getattr(obj, "property_owner", None)
        return owner == request.user



class IsAdminOrReadOnly(permissions.IsAdminUser):
    """Read for all, write only for admin/staff users."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Read for all; write only by property owner or staff."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "property_owner", None)
        return (owner is not None and owner == request.user) or bool(request.user and request.user.is_staff)





class HasAnyAdminRole(permissions.BasePermission):
    """
    Allows access to superusers, staff users, or users with an approved RentCrib admin role.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_staff", False):
            return True

        return user_has_any_admin_role(user)


class HasSpecificAdminRole(permissions.BasePermission):
    """
    Base class for role-specific admin access.
    Child classes must define allowed_admin_roles.
    """

    allowed_admin_roles = set()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        return user_has_admin_role(request.user, self.allowed_admin_roles)

class IsModerationAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "moderator"}


class IsOpsAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "ops_admin"}


class IsFinanceAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "finance_admin"}


class IsSupportAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "support_admin"}
