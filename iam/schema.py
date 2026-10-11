"""
TOUPAC IAM — Extensions drf-spectacular.

Sans cette extension, spectacular ne sait pas décrire ApiKeyAuthentication et
émet un avertissement par endpoint ; la référence Swagger n'annoncerait alors
que le Bearer JWT, laissant les intégrateurs sans documentation du header
`X-API-Key` qu'ils doivent pourtant utiliser.
"""
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class DenylistJWTScheme(SimpleJWTScheme):
    """
    Sous-classer JWTAuthentication a fait perdre à spectacular la
    correspondance vers son extension native — d'où un avertissement par
    endpoint depuis la mise en place du denylist. On la rétablit sous le nom
    `Bearer`, celui déclaré dans APPEND_COMPONENTS.
    """

    target_class = "iam.authentication.DenylistJWTAuthentication"
    name = "Bearer"


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "iam.api_key_authentication.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Clé API d'intégration, au format `prefix.secret`. Les droits sont "
                "portés par les scopes de la clé — voir /developers/#scopes."
            ),
        }


class CookieJWTAuthenticationScheme(SimpleJWTScheme):
    """`CookieJWTAuthentication` étend `DenylistJWTAuthentication` pour lire
    le JWT depuis le cookie HTTP-only `toupac_access` (fallback header
    Authorization). Mêmes garanties que `Bearer`, exposé sous le même nom
    au schéma pour que les intégrateurs n'aient pas à distinguer."""

    target_class = "iam.authentication_cookie.CookieJWTAuthentication"
    name = "Bearer"


class PlatformApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """Clé plateforme (prefix `tpc_platform_<hex>.<secret>`) — accompagnée
    du header `X-Tenant-ID` qui désigne le tenant visé par la requête."""

    target_class = "iam.platform_authentication.PlatformApiKeyAuthentication"
    name = "PlatformApiKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Clé plateforme, au format `tpc_platform_<hex>.<secret>`. "
                "Le header `X-Tenant-ID` doit accompagner la clé pour "
                "sélectionner le tenant visé."
            ),
        }
