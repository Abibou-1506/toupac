"""
TOUPAC IAM — Authentification par clé plateforme.

Troisième backend d'authentification, aux côtés du JWT (humains) et de la clé
tenant (`ApiKeyAuthentication`). Il sert les *services plateforme* : une clé
unique, valable pour tous les tenants abonnés au service, le tenant visé étant
donné par `X-Tenant-ID` à chaque requête.

Format du header : `X-API-Key: tpc_platform_<hex>.<secret>`.

Le préfixe distinct de celui des clés tenant (`tpc_`) n'est pas cosmétique : il
permet à ce backend de rendre la main **sans requête SQL** quand la clé
présentée est une clé tenant, et inversement d'être sûr qu'une clé plateforme ne
sera jamais résolue par le backend tenant.
"""
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from iam.models import PLATFORM_KEY_PREFIX, PlatformCredential, Tenant, TenantSubscription, User

#: Header portant le slug du tenant visé.
TENANT_HEADER = "HTTP_X_TENANT_ID"

#: Statuts de tenant qui acceptent du trafic API, alignés sur TenantMiddleware.
#: SUSPENDED reste exclu — c'est le levier de coupure commercial.
_SERVABLE_TENANT_STATUSES = (Tenant.Status.ACTIVE, Tenant.Status.TRIAL)


def client_ip(request):
    """
    IP source de la requête.

    `X-Forwarded-For` est une chaîne « client, proxy1, proxy2 » : la première
    entrée est le client d'origine. Elle n'est digne de confiance que parce que
    Caddy, en frontal, réécrit le header au lieu de le concaténer — un client
    qui forge son propre `X-Forwarded-For` voit sa valeur remplacée. Sans ce
    réglage côté reverse-proxy, l'allowlist IP serait contournable en une ligne.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class PlatformApiKeyAuthentication(BaseAuthentication):
    """Authentifie via une `PlatformCredential`. Retourne (platform_bot, credential)."""

    HEADER_NAME = "HTTP_X_API_KEY"

    def authenticate(self, request):
        raw = request.META.get(self.HEADER_NAME, "")
        if not raw.startswith(PLATFORM_KEY_PREFIX):
            # Absente, ou clé tenant : on rend la main sans toucher la base.
            return None

        if "." not in raw:
            raise exceptions.AuthenticationFailed(
                "Format de clé plateforme invalide (attendu : prefix.secret)."
            )

        prefix, secret = raw.split(".", 1)
        credential = PlatformCredential.objects.filter(key_prefix=prefix).first()
        # Message unique pour préfixe inconnu et secret faux : les distinguer
        # dirait à un attaquant quels préfixes existent.
        if credential is None or not check_password(secret, credential.key_hash):
            raise exceptions.AuthenticationFailed("Clé plateforme inconnue, révoquée ou invalide.")

        http_request = getattr(request, "_request", request)
        # Attachée avant les contrôles, et non après : le middleware d'audit doit
        # pouvoir journaliser un refus d'IP ou d'abonnement, qui sont justement
        # les appels qu'on veut voir passer.
        http_request.platform_credential = credential

        if not credential.is_active:
            raise exceptions.AuthenticationFailed("Clé plateforme révoquée.")
        if credential.expires_at <= timezone.now():
            raise exceptions.AuthenticationFailed(
                "Clé plateforme expirée. Contactez TOUPAC pour la rotation."
            )

        source_ip = client_ip(request)
        if not credential.allows_ip(source_ip, debug=settings.DEBUG):
            # 403 et non 401 : la clé est bonne, c'est l'origine qui est refusée.
            # Un 401 inviterait à re-tenter avec un autre secret.
            raise exceptions.PermissionDenied(
                f"IP source {source_ip} non autorisée pour cette clé plateforme."
            )

        self._attach_tenant_context(request, http_request, credential)

        PlatformCredential.objects.filter(pk=credential.pk).update(last_used_at=timezone.now())

        return (User.get_or_create_platform_bot(), credential)

    def _attach_tenant_context(self, request, http_request, credential):
        """
        Résout `X-Tenant-ID` et vérifie l'abonnement.

        Ce backend est autoritaire sur `request.tenant` : `TenantMiddleware` a pu
        poser une valeur depuis le même header (il l'interprète comme un UUID),
        et on ne veut pas qu'une requête plateforme hérite d'un tenant résolu par
        un chemin qui ne vérifie aucun abonnement. Absence de header = tenant
        remis à None, à charge des permissions d'exiger ou d'interdire le
        contexte selon l'endpoint.
        """
        # Remis à zéro d'entrée, et non seulement en l'absence d'en-tête :
        # depuis USR-2, `TenantMiddleware` sait résoudre un slug et a donc pu
        # poser un tenant avant nous. Le laisser en place ferait qu'une requête
        # refusée — abonnement manquant — conserverait le contexte visé, alors
        # que rien ne l'a accordé. Ce backend reste seul juge du tenant d'une
        # requête plateforme.
        http_request.tenant = None
        http_request.tenant_id = None

        slug = request.META.get(TENANT_HEADER, "").strip()
        if not slug:
            return

        tenant = Tenant.objects.filter(slug=slug, status__in=_SERVABLE_TENANT_STATUSES).first()
        if tenant is None:
            raise exceptions.PermissionDenied(
                f"Tenant « {slug} » inconnu ou inactif. Utilisez le slug retourné par "
                "GET /api/v1/platform/tenants/."
            )

        subscribed = TenantSubscription.objects.filter(
            tenant=tenant, platform_service=credential.platform_service, is_active=True,
        ).exists()
        if not subscribed:
            raise exceptions.PermissionDenied(
                f"Le tenant « {slug} » n'est pas abonné au service "
                f"« {credential.platform_service} »."
            )

        http_request.tenant = tenant
        http_request.tenant_id = tenant.id

    def authenticate_header(self, request):
        """Sans ça, DRF répond 403 au lieu de 401 sur une clé rejetée."""
        return "X-API-Key"
