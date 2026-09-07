"""
TOUPAC IAM — Endpoints réservés aux clés plateforme.

Deux familles, distinguées par `platform_required_scope` :

- **Globales** (`platform:global:read`) — sans contexte tenant, elles refusent
  `X-Tenant-ID`. Elles servent au service plateforme à se découvrir lui-même :
  sur quels tenants peut-il travailler, sa clé expire-t-elle bientôt.
- **Tenant-scopées** — elles exigent `X-Tenant-ID` et lisent les données du
  tenant visé.

Le contrat de header est tenu par `IsPlatformTenantContextValid`, branchée
globalement ; ces vues n'ont donc rien à vérifier elles-mêmes.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from iam.models import PlatformCredential, Tenant
from iam.platform_scopes import GLOBAL_SCOPE

_TAG = ["Plateforme"]


class PlatformTenantSerializer(serializers.Serializer):
    slug = serializers.SlugField()
    name = serializers.CharField()


class PlatformTenantsResponseSerializer(serializers.Serializer):
    tenants = PlatformTenantSerializer(many=True)


class PlatformHealthResponseSerializer(serializers.Serializer):
    platform_service = serializers.CharField()
    # Nuls tous les deux pour une clé sans échéance, ce qui est le cas nominal.
    expires_at = serializers.DateTimeField(allow_null=True)
    days_until_expiry = serializers.IntegerField(allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField())


@extend_schema(tags=_TAG, responses=PlatformTenantsResponseSerializer)
class PlatformTenantsView(APIView):
    """
    GET /api/v1/platform/tenants/ — compagnies auxquelles la clé donne accès.

    C'est la découverte dynamique promise à l'équipe partenaire : une compagnie
    nouvellement créée apparaît ici sans qu'elle redéploie quoi que ce soit, et
    sans démarche d'habilitation.
    """

    platform_endpoint_type = "global"
    platform_required_scope = GLOBAL_SCOPE

    def get(self, request):
        # Toutes les compagnies actives, sans habilitation préalable : un
        # service plateforme est une fonctionnalité de TOUPAC, disponible dès
        # qu'une compagnie existe. Les suspendues sont exclues — les proposer
        # reviendrait à annoncer un service qui refusera les appels.
        tenants = Tenant.objects.filter(
            status__in=[Tenant.Status.ACTIVE, Tenant.Status.TRIAL],
        ).order_by("name")
        return Response({
            "tenants": [{"slug": t.slug, "name": t.name} for t in tenants],
        })


@extend_schema(tags=_TAG, responses=PlatformHealthResponseSerializer)
class PlatformHealthView(APIView):
    """
    GET /api/v1/platform/health/ — état de la clé courante.

    Permet au partenaire de surveiller lui-même l'échéance de rotation plutôt
    que de découvrir l'expiration par une vague de 401.
    """

    platform_endpoint_type = "global"
    platform_required_scope = GLOBAL_SCOPE

    def get(self, request):
        credential: PlatformCredential = request.auth
        return Response({
            "platform_service": credential.platform_service,
            "expires_at": credential.expires_at,
            "days_until_expiry": credential.days_until_expiry,
            "scopes": list(credential.platform_scopes or []),
        })


class PlatformNotificationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_code = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    priority = serializers.CharField()
    read_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


@extend_schema(tags=_TAG, responses=PlatformNotificationSerializer(many=True))
class PlatformNotificationsView(APIView):
    """
    GET /api/v1/platform/notifications/ — centre d'alertes du tenant visé.

    Aperçu V1 : les 50 dernières notifications du tenant. La version complète
    (filtres, pagination, marquage lu) arrive au Ticket D de la refonte notifs ;
    cet endpoint existe pour que le contrat de scope
    `platform:notifications:read` soit exerçable dès maintenant.
    """

    platform_endpoint_type = "tenant"
    platform_required_scope = "platform:notifications:read"

    def get(self, request):
        from notifications.models import Notification

        queryset = (
            Notification.objects.filter(tenant=request.tenant).order_by("-created_at")[:50]
        )
        return Response(PlatformNotificationSerializer(queryset, many=True).data)
