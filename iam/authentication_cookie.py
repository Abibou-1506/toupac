"""Authentication class qui lit le JWT access depuis un cookie HTTP-only.

Encapsule DenylistJWTAuthentication en synthétisant un header Bearer
depuis le cookie toupac_access, pour que la logique de validation
existante (denylist access tokens, scopes, etc.) continue à fonctionner
sans duplication.
"""
from iam.authentication import DenylistJWTAuthentication


class CookieJWTAuthentication(DenylistJWTAuthentication):
    """Lit l'access token depuis le cookie toupac_access en priorité."""

    def authenticate(self, request):
        access = request.COOKIES.get("toupac_access")
        if access and not request.META.get("HTTP_AUTHORIZATION"):
            request.META["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        return super().authenticate(request)
