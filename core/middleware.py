"""
TOUPAC Core — Middleware multi-tenant.
Extrait le tenant_id du JWT ou de la session et l'attache à request.tenant.
"""
import jwt
from django.core.exceptions import ValidationError
from django.utils.deprecation import MiddlewareMixin

PUBLIC_PATH_PREFIXES = (
    "/admin/login",
    "/api/v1/auth/login",
    "/health",
    "/api/v1/billing/payments/webhook",
)


class TenantMiddleware(MiddlewareMixin):
    """
    Résout le tenant depuis :
    - Session Django (admin web, authentifiée avant ce middleware)
    - Claim `tenant_id` du JWT (API mobile/externe) — décodé SANS validation
      de signature : simplejwt fait la vraie validation plus tard, au niveau
      DRF. Ce middleware tourne avant l'authentification DRF, donc
      request.user est encore AnonymousUser pour les requêtes JWT ; lire le
      claim directement est le seul moyen de connaître le tenant ici.
    - Header X-Tenant-Id (dev/tests uniquement)

    Attache request.tenant (instance Tenant) et request.tenant_id (UUID).
    Les vues non-authentifiées (login, health, webhook paiement) passent
    avec tenant=None.
    """

    def process_request(self, request):
        request.tenant = None
        request.tenant_id = None

        if request.path.startswith(PUBLIC_PATH_PREFIXES):
            return

        # 1. Session Django (admin web)
        if hasattr(request, "user") and request.user.is_authenticated:
            tenant = getattr(request.user, "tenant", None)
            if tenant:
                request.tenant = tenant
                request.tenant_id = tenant.id
                return

        # 2. Claim tenant_id du JWT (API — non encore authentifiée ici)
        if self._resolve_from_jwt(request):
            return

        # 3. Header explicite (dev/tests uniquement)
        self._resolve_from_header(request)

    def _resolve_from_jwt(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return False

        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            return False

        return self._attach_tenant(request, tenant_id)

    def _resolve_from_header(self, request):
        tenant_header = request.META.get("HTTP_X_TENANT_ID")
        if tenant_header:
            self._attach_tenant(request, tenant_header)

    @staticmethod
    def _attach_tenant(request, tenant_id):
        from iam.models import Tenant

        # TRIAL est un tenant qui paie en essai commercial : il doit pouvoir
        # utiliser l'API. SUSPENDED reste exclu — c'est le levier de coupure.
        allowed = (Tenant.Status.ACTIVE, Tenant.Status.TRIAL)
        try:
            tenant = Tenant.objects.get(id=tenant_id, status__in=allowed)
        except (Tenant.DoesNotExist, ValueError, ValidationError):
            return False

        request.tenant = tenant
        request.tenant_id = tenant.id
        return True
