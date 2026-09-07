"""
TOUPAC IAM — Endpoints du client TOUPAC.

Un client est global : il n'appartient à aucune compagnie et peut réserver chez
plusieurs. Ces vues sont donc les seules du projet à ne jamais filtrer par
`request.tenant` — elles répondent sur la personne, pas sur la compagnie.

Sur le filtrage : `TenantManager` ne filtre rien de lui-même — ce sont les
ViewSets métier qui appellent `.filter(tenant=request.tenant)`. Ces vues-ci
s'en abstiennent délibérément, et restreignent à la place sur le lien vers le
client (`passenger__customer_user`, `order.customer`, `invoice.customer_id`).
C'est ce lien qui porte l'isolation ici, et il est aussi strict : un client ne
voit que ce qui le désigne nommément.
"""
from datetime import date

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from iam.customer_serializers import (
    MyOrderSerializer,
    MyPaymentSerializer,
    MyReservationSerializer,
)
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


class CustomerStatsSerializer(serializers.Serializer):
    total_reservations = serializers.IntegerField()
    total_orders = serializers.IntegerField()


class CustomerProfileSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField(allow_null=True)
    phone = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    notification_preferences = serializers.DictField()
    has_email = serializers.BooleanField()
    has_phone = serializers.BooleanField()
    stats = CustomerStatsSerializer()


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
        from colis.models import Order
        from voyage.models import Reservation

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
            "stats": {
                # Compté sur les réservations, pas sur les fiches passager :
                # une même personne a une fiche par compagnie, les additionner
                # donnerait un total qui ne veut rien dire.
                "total_reservations": Reservation.objects.filter(
                    passenger__customer_user=user,
                    passenger__deleted_at__isnull=True,
                ).count(),
                "total_orders": Order.objects.filter(
                    customer=user, deleted_at__isnull=True,
                ).count(),
            },
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


# ─── Historique transverse aux compagnies ───

_TENANT_PARAM = OpenApiParameter(
    "tenant", str, description="Slug d'une compagnie, pour ne garder que ses éléments.",
)
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtre sur le statut.")


@extend_schema(
    tags=_TAG,
    parameters=[
        _TENANT_PARAM, _STATUS_PARAM,
        OpenApiParameter(
            "upcoming", bool,
            description="`true` pour ne garder que les voyages à partir d'aujourd'hui.",
        ),
    ],
    responses=MyReservationSerializer(many=True),
)
class MyReservationsView(APIView):
    """
    GET /api/v1/customer/my-reservations/ — les voyages du client, toutes compagnies.

    Le lien passe par la fiche passager : une réservation appartient au client
    quand la fiche du voyageur est rattachée à son compte. Réserver pour
    quelqu'un d'autre ne fait donc pas apparaître le billet chez soi — c'est
    bien le voyageur qui le voit, pas l'acheteur.
    """

    permission_classes = [IsAuthenticatedCustomer]

    def get(self, request):
        from voyage.models import Reservation

        queryset = (
            Reservation.objects
            .filter(
                passenger__customer_user=request.user,
                # Une fiche effacée au titre du RGPD ne doit plus rien afficher.
                passenger__deleted_at__isnull=True,
            )
            .select_related("tenant", "trip", "trip__route", "passenger")
            .order_by("-trip__departure_date", "-created_at")
        )

        tenant_slug = request.query_params.get("tenant")
        if tenant_slug:
            queryset = queryset.filter(tenant__slug=tenant_slug)
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if request.query_params.get("upcoming") == "true":
            queryset = queryset.filter(trip__departure_date__gte=date.today())

        return Response({"reservations": MyReservationSerializer(queryset, many=True).data})


@extend_schema(
    tags=_TAG,
    parameters=[_TENANT_PARAM, _STATUS_PARAM],
    responses=MyOrderSerializer(many=True),
)
class MyOrdersView(APIView):
    """
    GET /api/v1/customer/my-orders/ — les colis commandés par le client.

    Seul le commanditaire est modélisé : un client destinataire d'un colis
    qu'un autre a expédié ne le voit pas ici. Asymétrie assumée en V1, tracée
    dans DETTES.md.
    """

    permission_classes = [IsAuthenticatedCustomer]

    def get(self, request):
        from colis.models import Order

        queryset = (
            Order.objects
            .filter(customer=request.user, deleted_at__isnull=True)
            .select_related("tenant", "pickup_place", "dropoff_place")
            .order_by("-created_at")
        )

        tenant_slug = request.query_params.get("tenant")
        if tenant_slug:
            queryset = queryset.filter(tenant__slug=tenant_slug)
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return Response({"orders": MyOrderSerializer(queryset, many=True).data})


@extend_schema(tags=_TAG, parameters=[_TENANT_PARAM], responses=MyPaymentSerializer(many=True))
class MyPaymentsView(APIView):
    """
    GET /api/v1/customer/my-payments/ — ce que le client a réglé.

    Deux chemins mènent à un paiement : la commande de colis dont il est
    commanditaire, et la facture qui le désigne. `Payment` ne porte pas de lien
    direct vers un payeur — l'ajouter dupliquerait une information que ces deux
    relations donnent déjà.

    Être passager d'un billet ne suffit pas : un billet réglé par un proche
    apparaît dans les voyages du client, jamais dans ses paiements.
    """

    permission_classes = [IsAuthenticatedCustomer]

    def get(self, request):
        from billing.models import CUSTOMER_TYPE_CLIENT_USER, Payment

        queryset = (
            Payment.objects
            .filter(
                Q(order__customer=request.user, order__deleted_at__isnull=True)
                # `customer_type` est indispensable : sans lui, l'identifiant
                # d'un client externe qui coïnciderait avec celui d'un compte
                # TOUPAC ouvrirait la facture d'un tiers.
                | Q(
                    invoice__customer_id=request.user.id,
                    invoice__customer_type=CUSTOMER_TYPE_CLIENT_USER,
                )
            )
            .select_related("tenant", "order", "invoice", "reservation")
            .order_by("-initiated_at")
            # Les deux branches peuvent désigner le même paiement (une commande
            # facturée au même client) : sans quoi il apparaîtrait deux fois.
            .distinct()
        )

        tenant_slug = request.query_params.get("tenant")
        if tenant_slug:
            queryset = queryset.filter(tenant__slug=tenant_slug)

        return Response({"payments": MyPaymentSerializer(queryset, many=True).data})
