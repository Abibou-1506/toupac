from rest_framework.permissions import BasePermission


class IsTenantUser(BasePermission):
    """Vérifie que l'utilisateur appartient au tenant courant."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.tenant is not None
            and request.user.tenant_id == request.tenant.id
        )


class HasRole(BasePermission):
    """Vérifie que l'utilisateur a un des rôles requis."""
    required_roles = []

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = getattr(view, "required_roles", self.required_roles)
        return request.user.role in required
