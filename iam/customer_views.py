"""
TOUPAC IAM — Endpoints du client TOUPAC.

Un client est global : il n'appartient à aucune compagnie et peut réserver chez
plusieurs. Ces vues sont donc les seules du projet à ne jamais filtrer par
`request.tenant` — elles répondent sur la personne, pas sur la compagnie.

USR-2 en livre deux. Les endpoints d'historique (`my-reservations`,
`my-orders`, `my-payments`) attendent USR-3, qui donne aux modèles métier des
clés étrangères vers un client hors compagnie.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from iam.models import Tenant, User

_TAG = ["Client"]


class IsAuthenticatedCustomer(IsAuthenticated):
    """
    Authentifié **et** client TOUPAC.

    Le rôle est vérifié en plus de l'authentification : ces vues répondent sans
    aucun filtre de compagnie, les ouvrir à un membre du personnel lui donnerait
    une vue transverse qu'aucun autre endpoint ne lui accorde.
    """

    message = "Réservé aux comptes clients TOUPAC."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return getattr(request.user, "role", None) == User.Role.CLIENT


class CustomerProfileSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField(allow_null=True)
    phone = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    notification_preferences = serializers.DictField()
    has_email = serializers.BooleanField()
    has_phone = serializers.BooleanField()


class CustomerCompanySerializer(serializers.Serializer):
    slug = serializers.SlugField()
    name = serializers.CharField()
    country_code = serializers.CharField()


class CustomerCompaniesResponseSerializer(serializers.Serializer):
    companies = CustomerCompanySerializer(many=True)


@extend_schema(tags=_TAG, responses=CustomerProfileSerializer)
class CustomerMeView(APIView):
    """
    GET /api/v1/customer/me/ — profil du client connecté.

    Se distingue de `/auth/me/` par deux ajouts utiles aux clients de l'API :
    les préférences de notification, et `has_email` / `has_phone`, qui disent
    au chatbot par quel canal il peut proposer une connexion sans avoir à
    manipuler les valeurs elles-mêmes.
    """

    permission_classes = [IsAuthenticatedCustomer]

    def get(self, request):
        user = request.user
        return Response(CustomerProfileSerializer({
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "notification_preferences": user.notification_preferences or {},
            "has_email": bool(user.email),
            "has_phone": bool(user.phone),
        }).data)


@extend_schema(tags=_TAG, responses=CustomerCompaniesResponseSerializer)
class CustomerCompaniesListView(APIView):
    """
    GET /api/v1/customer/companies/ — compagnies chez qui réserver.

    Les compagnies suspendues sont exclues : proposer une compagnie qui refusera
    la réservation ferait porter au client une panne commerciale. Le statut
    d'essai reste visible, c'est un client qui paie.
    """

    permission_classes = [IsAuthenticatedCustomer]

    def get(self, request):
        tenants = Tenant.objects.filter(
            status__in=[Tenant.Status.ACTIVE, Tenant.Status.TRIAL],
        ).order_by("name")
        return Response({
            "companies": CustomerCompanySerializer(tenants, many=True).data,
        })
