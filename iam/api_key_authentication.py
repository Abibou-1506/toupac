"""
TOUPAC IAM — Authentification par clé API.

Deux systèmes d'authentification coexistent : le JWT pour les humains (app
mobile, back-office) et la clé API pour les intégrations tierces (chatbot,
ERP). La clé API porte des scopes, vérifiés par `iam.permissions.HasApiScope`.

Format du header : `X-API-Key: <prefix>.<secret>`. Le préfixe identifie la
ligne en base, le secret est comparé à son hash.
"""
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from iam.models import ApiCredential


class ApiKeyAuthentication(BaseAuthentication):
    """Authentifie via `X-API-Key`. Retourne (user, credential)."""

    HEADER_NAME = "HTTP_X_API_KEY"

    def authenticate(self, request):
        raw = request.META.get(self.HEADER_NAME)
        if not raw:
            # Pas de clé API : on laisse la main aux autres authentificateurs.
            return None

        if "." not in raw:
            raise AuthenticationFailed("Format de clé API invalide (attendu : prefix.secret).")

        prefix, secret = raw.split(".", 1)
        credential = (
            ApiCredential.objects.select_related("tenant", "user")
            .filter(key_prefix=prefix, is_active=True)
            .first()
        )
        # Message unique pour préfixe inconnu et secret faux : distinguer les
        # deux dirait à un attaquant quels préfixes existent.
        if credential is None or not check_password(secret, credential.key_hash):
            raise AuthenticationFailed("Clé API inconnue, révoquée ou invalide.")

        if credential.expires_at and credential.expires_at < timezone.now():
            raise AuthenticationFailed("Clé API expirée.")

        if credential.user is None:
            # user est SET_NULL : la suppression du porteur rend la clé
            # inutilisable. Le dire explicitement évite un 401 opaque, car
            # sans user IsAuthenticated échouerait de toute façon.
            raise AuthenticationFailed("Clé API orpheline : son utilisateur porteur n'existe plus.")

        # .update() plutôt que .save() : évite auto_now sur updated_at et les
        # signaux, pour une écriture par requête aussi légère que possible.
        ApiCredential.objects.filter(pk=credential.pk).update(last_used_at=timezone.now())

        # TenantMiddleware tourne avant l'authentification DRF : pour une
        # requête par clé API il n'a ni JWT ni session à lire et laisse
        # request.tenant à None, ce qui viderait toutes les querysets. Le
        # tenant n'est connu qu'ici, une fois la clé vérifiée. On le pose sur
        # la HttpRequest sous-jacente, d'où la Request DRF le relaie.
        http_request = getattr(request, "_request", request)
        http_request.tenant = credential.tenant
        http_request.tenant_id = credential.tenant_id

        return (credential.user, credential)

    def authenticate_header(self, request):
        """Sans ça, DRF répond 403 au lieu de 401 sur une clé rejetée."""
        return "X-API-Key"
