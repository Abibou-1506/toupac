"""
TOUPAC IAM — Journalisation des appels portés par une clé plateforme.

Mitigation n°4 de la note de design : une entrée par requête, succès **comme
échec**. Un refus d'IP ou une tentative sur un tenant non abonné sont exactement
les événements qu'on veut voir dans le journal — un log qui ne garderait que les
200 raterait la compromission qu'il est censé détecter.

Pourquoi un middleware plutôt qu'un hook DRF : `status_code` et latence ne sont
connus qu'une fois la réponse produite, et les rejets d'authentification se
produisent avant que la vue n'existe. Aucun point d'accroche DRF ne voit les
deux. `PlatformApiKeyAuthentication` pose `request.platform_credential` dès que
la clé est résolue — donc avant les contrôles qui peuvent la rejeter — pour que
la phase réponse retrouve la clé même sur un 401 ou un 403.
"""
import logging
import time

from iam.platform_authentication import client_ip

logger = logging.getLogger("toupac.iam.platform")


class PlatformAuditMiddleware:
    """Écrit un `PlatformAuditLog` pour chaque requête authentifiée par clé plateforme."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)

        credential = getattr(request, "platform_credential", None)
        if credential is not None:
            self._record(request, response, credential, started)
        return response

    @staticmethod
    def _acting_user(request):
        """
        Le client représenté, ou None.

        Reconnu par son rôle et non par comparaison au porteur technique : le
        rôle est la propriété qui compte, et s'y fier évite de coder en dur
        l'adresse du bot à un deuxième endroit.
        """
        from iam.models import User

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return user if user.role == User.Role.CLIENT else None

    @staticmethod
    def _record(request, response, credential, started):
        from iam.models import PlatformAuditLog

        latency_ms = int((time.monotonic() - started) * 1000)
        source_ip = client_ip(request) or "0.0.0.0"
        try:
            PlatformAuditLog.objects.create(
                credential=credential,
                acting_user=PlatformAuditMiddleware._acting_user(request),
                # request.tenant n'est posé que si la résolution a abouti : sur
                # un refus d'abonnement le contexte reste vide, ce qui est
                # l'information utile (« a tenté sans y avoir droit »).
                tenant_context=getattr(request, "tenant", None),
                endpoint=request.path[:200],
                method=request.method[:10],
                ip=source_ip,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                status_code=response.status_code,
                latency_ms=latency_ms,
            )
        except Exception:
            # Le journal ne doit jamais casser la requête qu'il observe : une
            # base saturée rendrait l'API indisponible au lieu de dégradée.
            logger.exception(
                "Échec d'écriture du PlatformAuditLog (clé %s, %s %s)",
                credential.key_prefix, request.method, request.path,
            )
