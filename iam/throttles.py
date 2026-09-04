"""
TOUPAC IAM — Rate limiting par clé API.

Deux throttles mutuellement exclusifs : une requête donnée est comptée par
l'un ou par l'autre, jamais les deux. DRF applique *tous* les throttles
déclarés — il n'y a pas de court-circuit sur le premier qui renvoie None —
donc si le throttle standard s'appliquait aussi aux clés admin, celles-ci
seraient plafonnées au taux standard et le taux généreux ne servirait à rien.

Les taux viennent de DEFAULT_THROTTLE_RATES (via `scope`), pas d'un
`get_rate()` codé en dur : sinon les réglages du settings seraient ignorés.
"""
from django.core.cache import DEFAULT_CACHE_ALIAS, caches
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

from iam.models import ApiCredential
from iam.scopes import ADMIN_SCOPE


class _BaseApiKeyThrottle(SimpleRateThrottle):
    """Compte par préfixe de clé. Ne s'applique qu'aux requêtes par clé API."""

    #: True pour ne compter que les clés admin, False pour toutes les autres.
    admin_keys_only = False

    @property
    def cache(self):
        """
        Résolution tardive du cache.

        SimpleRateThrottle fige `cache` en attribut de classe à l'import : il
        garde alors une référence au backend d'origine et ignore tout
        changement ultérieur de CACHES. En tests, les compteurs partaient dans
        le Redis de dev au lieu du cache isolé, et le polluaient.
        """
        return caches[DEFAULT_CACHE_ALIAS]

    def get_rate(self):
        """
        Résolution tardive du taux, pour la même raison.

        `SimpleRateThrottle.THROTTLE_RATES` est lui aussi figé à l'import :
        modifier DEFAULT_THROTTLE_RATES après coup n'avait aucun effet, ce qui
        rendait le réglage du settings trompeur — il fallait redémarrer pour
        qu'un changement de quota s'applique.
        """
        rates = api_settings.DEFAULT_THROTTLE_RATES
        if self.scope in rates:
            return rates[self.scope]
        return super().get_rate()  # ImproperlyConfigured avec le message DRF

    def get_cache_key(self, request, view):
        credential = request.auth
        if not isinstance(credential, ApiCredential):
            return None  # JWT ou session : hors de ce mécanisme
        if credential.has_scope(ADMIN_SCOPE) is not self.admin_keys_only:
            return None
        return f"throttle_{self.scope}_{credential.key_prefix}"


class ApiKeyRateThrottle(_BaseApiKeyThrottle):
    """Taux standard, pour les clés à scopes restreints (partenaires)."""

    scope = "api_key_default"
    admin_keys_only = False


class ApiKeyAdminRateThrottle(_BaseApiKeyThrottle):
    """Taux généreux, réservé aux clés portant `admin:*` (SI interne)."""

    scope = "api_key_admin"
    admin_keys_only = True
