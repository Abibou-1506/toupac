"""
TOUPAC IAM — Authentification JWT avec denylist des access tokens.

simplejwt sait révoquer un refresh token (table blacklist), pas un access
token : celui-ci reste valable jusqu'à son `exp`, donc un token volé survit
au logout. On stocke ici son `jti` en cache avec un TTL calé sur le temps
restant avant expiration naturelle — passé ce délai l'entrée disparaît d'
elle-même, sans tâche de purge, et le token serait de toute façon refusé
par la validation d'expiration.
"""
import time

from django.core.cache import cache
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

ACCESS_TOKEN_DENYLIST_PREFIX = "access_denylist:"


def _denylist_key(jti):
    return f"{ACCESS_TOKEN_DENYLIST_PREFIX}{jti}"


def deny_access_token(jti, ttl_seconds):
    """
    Ajoute un jti au denylist, pour `ttl_seconds` secondes.

    Un TTL nul ou négatif signifie que le token est déjà expiré : le stocker
    n'apporterait rien, la validation d'expiration le rejette déjà.
    """
    if not jti or ttl_seconds <= 0:
        return
    cache.set(_denylist_key(jti), "1", timeout=ttl_seconds)


def deny_token_until_expiry(token):
    """
    Révoque un access token validé (instance simplejwt) jusqu'à son `exp`.

    Sans effet si le token est absent — `request.auth` vaut None quand la
    requête est authentifiée par session (admin, API navigable).
    """
    if token is None:
        return
    jti, exp = token.get("jti"), token.get("exp")
    if not jti or not exp:
        return
    deny_access_token(jti, int(exp - time.time()))


def is_access_token_denied(jti):
    return bool(jti) and cache.get(_denylist_key(jti)) is not None


class DenylistJWTAuthentication(JWTAuthentication):
    """JWTAuthentication rejetant les access tokens révoqués au logout."""

    def get_validated_token(self, raw_token):
        # super() d'abord : un token expiré ou mal signé doit garder son
        # erreur d'origine, `token_revoked` ne concerne que les tokens
        # par ailleurs valides.
        validated_token = super().get_validated_token(raw_token)
        if is_access_token_denied(validated_token.get("jti")):
            raise AuthenticationFailed("Token révoqué (déconnexion).", code="token_revoked")
        return validated_token
