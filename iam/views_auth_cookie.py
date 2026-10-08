"""Vues d'auth qui déposent les tokens JWT dans des cookies HTTP-only.

SimpleJWT par défaut retourne les tokens dans le body JSON — on les
intercepte et on les met dans des cookies pour que le front n'ait
jamais à manipuler le token lui-même. Mitige XSS en garantissant que
le token n'est pas accessible depuis JavaScript.

Cookies :
- toupac_access : access token, httponly, secure (prod), samesite=Lax
- toupac_refresh : refresh token, httponly, secure (prod), samesite=Lax,
  path=/api/v1/auth/

Le path restreint du refresh réduit sa surface d'exposition.
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import ToupacTokenObtainSerializer


def _set_jwt_cookies(response, access, refresh):
    """Dépose les tokens dans des cookies HTTP-only sur la réponse.

    Le flag `secure` suit `SESSION_COOKIE_SECURE` (pattern Django canonique)
    au lieu de dériver de `DEBUG`. Permet le staging HTTP (secure=False via
    `settings.staging.py`) sans toucher au code. Prod HTTPS garde
    `secure=True` via `SESSION_COOKIE_SECURE=True` dans `settings.prod.py`.
    Dev inchangé (DEBUG=True + SESSION_COOKIE_SECURE non défini → False).
    """
    secure = settings.SESSION_COOKIE_SECURE
    access_lifetime = settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    refresh_lifetime = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]

    if access:
        response.set_cookie(
            "toupac_access",
            access,
            max_age=int(access_lifetime.total_seconds()),
            httponly=True,
            secure=secure,
            samesite="Lax",
        )
    if refresh:
        response.set_cookie(
            "toupac_refresh",
            refresh,
            max_age=int(refresh_lifetime.total_seconds()),
            httponly=True,
            secure=secure,
            samesite="Lax",
            path="/api/v1/auth/",
        )
    return response


class CookieTokenObtainPairView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — login JWT qui dépose aussi les tokens dans des cookies.

    Les tokens restent dans le body JSON (contrat historique utilisé par les
    clients mobiles et les tests) ; en plus, ils sont déposés comme cookies
    HTTP-only pour que toupac-web n'ait jamais à les manipuler.
    """

    serializer_class = ToupacTokenObtainSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 200 and isinstance(response.data, dict):
            access = response.data.get("access")
            refresh = response.data.get("refresh")
            _set_jwt_cookies(response, access, refresh)
        return response


class CookieTokenRefreshView(TokenRefreshView):
    """POST /api/v1/auth/refresh/ — accepte le refresh via body OU cookie, redépose les cookies."""

    def post(self, request, *args, **kwargs):
        # Fallback cookie uniquement si body ne fournit pas déjà le refresh.
        body_refresh = None
        if isinstance(getattr(request, "data", None), dict):
            body_refresh = request.data.get("refresh")

        cookie_refresh = request.COOKIES.get("toupac_refresh")
        if not body_refresh and cookie_refresh:
            try:
                request.data["refresh"] = cookie_refresh
            except (TypeError, AttributeError):
                request._full_data = {"refresh": cookie_refresh}  # noqa: SLF001

        if not body_refresh and not cookie_refresh:
            return Response(
                {"detail": "Refresh token absent."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response = super().post(request, *args, **kwargs)
        if response.status_code == 200 and isinstance(response.data, dict):
            new_access = response.data.get("access")
            new_refresh = response.data.get("refresh", cookie_refresh or body_refresh)
            _set_jwt_cookies(response, new_access, new_refresh)
        return response


class CookieLogoutView(APIView):
    """POST /api/v1/auth/logout/ — blackliste le refresh (body ou cookie) et efface les cookies.

    Reprend le contrat de l'ancienne LogoutView (IsAuthenticated, deny access
    courant, 400 si refresh body malformé) et ajoute l'effacement des cookies
    HTTP-only côté client.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from iam.authentication import deny_token_until_expiry

        body_refresh = None
        if isinstance(getattr(request, "data", None), dict):
            body_refresh = request.data.get("refresh")
        cookie_refresh = request.COOKIES.get("toupac_refresh")

        try:
            if body_refresh:
                RefreshToken(body_refresh).blacklist()
            elif cookie_refresh:
                # Le cookie étant toujours posé par nous, un échec silencieux
                # garde l'idempotence du logout — le client n'a jamais vu le
                # jeton et ne peut pas corriger.
                try:
                    RefreshToken(cookie_refresh).blacklist()
                except Exception:
                    pass

            # Révoque l'access courant comme la LogoutView historique.
            deny_token_until_expiry(request.auth)
        except Exception:
            return Response({"detail": "Token invalide."}, status=status.HTTP_400_BAD_REQUEST)

        response = Response({"detail": "Déconnexion réussie."}, status=200)
        response.delete_cookie("toupac_access")
        response.delete_cookie("toupac_refresh", path="/api/v1/auth/")
        return response
