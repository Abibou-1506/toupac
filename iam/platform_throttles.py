"""
TOUPAC IAM — Rate limiting des clés plateforme.

Compteur séparé de celui des clés tenant : une clé plateforme sert N tenants,
mélanger les deux quotas ferait qu'un service plateforme actif épuiserait le
budget au nom d'une compagnie. Même résolution tardive du cache et du taux que
`iam.throttles` — voir les commentaires détaillés là-bas.
"""
from django.core.cache import DEFAULT_CACHE_ALIAS, caches
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

from iam.models import PlatformCredential


class PlatformKeyRateThrottle(SimpleRateThrottle):
    """Compte par préfixe de clé plateforme. Sans effet sur les autres requêtes."""

    scope = "platform_key_default"

    @property
    def cache(self):
        return caches[DEFAULT_CACHE_ALIAS]

    def get_rate(self):
        rates = api_settings.DEFAULT_THROTTLE_RATES
        if self.scope in rates:
            return rates[self.scope]
        return super().get_rate()

    def get_cache_key(self, request, view):
        credential = request.auth
        if not isinstance(credential, PlatformCredential):
            return None
        return f"throttle_{self.scope}_{credential.key_prefix}"
