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
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from iam.models import PLATFORM_KEY_PREFIX, PlatformCredential, Tenant, User

#: Header portant le slug du tenant visé.
TENANT_HEADER = "HTTP_X_TENANT_ID"

#: Headers désignant le client au nom duquel le service agit.
ACTING_EMAIL_HEADER = "HTTP_X_ACTING_USER_EMAIL"
ACTING_PHONE_HEADER = "HTTP_X_ACTING_USER_PHONE"

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
        if credential.is_expired():
            raise exceptions.AuthenticationFailed(
                "Clé plateforme expirée. Contactez TOUPAC pour en obtenir une nouvelle."
            )

        source_ip = client_ip(request)
        if not credential.allows_ip(source_ip):
            # 403 et non 401 : la clé est bonne, c'est l'origine qui est refusée.
            # Un 401 inviterait à re-tenter avec un autre secret.
            raise exceptions.PermissionDenied(
                f"IP source {source_ip} non autorisée pour cette clé plateforme."
            )

        self._attach_tenant_context(request, http_request)

        PlatformCredential.objects.filter(pk=credential.pk).update(last_used_at=timezone.now())

        return (self._resolve_principal(request), credential)

    @staticmethod
    def _resolve_principal(request):
        """
        Qui la requête représente : un client désigné, ou le porteur technique.

        Un service plateforme n'agit presque jamais pour lui-même — il traduit
        la demande d'une personne. `X-Acting-User-Email` (ou
        `X-Acting-User-Phone`) désigne cette personne, et c'est elle qui devient
        `request.user` : les vues client, les filtres et la trace d'audit
        parlent alors du bon compte sans rien connaître du partenaire.

        Le compte est créé s'il n'existe pas. C'est voulu : pour un passager,
        s'inscrire et être servi sont le même geste, et il retrouvera plus tard
        ce même compte par la connexion par code (USR-2).

        Sans en-tête, on retombe sur le porteur technique global — le seul cas
        légitime étant les endpoints qui ne concernent personne en particulier
        (liste des compagnies, santé de la clé).
        """
        email = (request.META.get(ACTING_EMAIL_HEADER) or "").strip().lower() or None
        phone = (request.META.get(ACTING_PHONE_HEADER) or "").strip() or None

        if not email and not phone:
            return User.get_or_create_platform_bot()

        try:
            # Priorité à l'e-mail quand les deux sont fournis — même règle que
            # la connexion par code, une seule doctrine de résolution.
            acting_user, _ = User.get_or_create_client(email=email, phone=phone)
        except ValueError as exc:
            # L'identifiant appartient à un compte d'exploitation : on refuse
            # sans dire à qui, et sans créer de client.
            raise exceptions.PermissionDenied(str(exc)) from exc
        return acting_user

    def _attach_tenant_context(self, request, http_request):
        """
        Résout `X-Tenant-ID`.

        Ce backend est autoritaire sur `request.tenant` : `TenantMiddleware` a
        pu poser une valeur depuis le même en-tête, et une requête refusée ne
        doit pas conserver un contexte que rien ne lui a accordé. D'où la remise
        à zéro d'entrée, avant toute résolution.

        Aucune vérification d'habilitation par compagnie : un service plateforme
        est une fonctionnalité de TOUPAC, ouverte à toute compagnie active dès
        sa création. Le cloisonnement passe par les scopes de la clé, pas par
        une liste d'abonnées.
        """
        http_request.tenant = None
        http_request.tenant_id = None

        slug = (request.META.get(TENANT_HEADER) or "").strip()
        if not slug:
            return

        tenant = Tenant.objects.filter(slug=slug, status__in=_SERVABLE_TENANT_STATUSES).first()
        if tenant is None:
            raise exceptions.PermissionDenied(
                f"Compagnie « {slug} » inconnue ou inactive. Utilisez un slug retourné "
                "par GET /api/v1/platform/tenants/."
            )

        http_request.tenant = tenant
        http_request.tenant_id = tenant.id

    def authenticate_header(self, request):
        """Sans ça, DRF répond 403 au lieu de 401 sur une clé rejetée."""
        return "X-API-Key"
