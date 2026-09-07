"""
TOUPAC IAM — Centre d'alertes du client TOUPAC.

Séparé de `customer_views.py`, qui rassemble l'historique en lecture seule. Ces
vues-ci écrivent — marquer lu, acquitter — et introduisent la pagination, seule
du projet côté client. Deux préoccupations distinctes, deux fichiers.

L'isolation ne passe par aucune compagnie : une notification appartient à son
destinataire, `recipient_user`. Un client en reçoit de plusieurs transporteurs,
et son centre d'alertes les rassemble — c'est le même parti que
`/customer/my-reservations/`, à ceci près qu'ici le lien est direct.

Une notification qui ne vise pas l'appelant se répond **404, jamais 403** : un
403 confirmerait qu'elle existe, et l'identifiant suffirait alors à sonder le
système.
"""
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from iam.customer_serializers import MyNotificationSerializer
from iam.customer_views import (
    _CUSTOMER_AUTH,
    _CUSTOMER_THROTTLES,
    IsAuthenticatedCustomer,
)

_TAG = ["Client"]


class NotificationsPagination(PageNumberPagination):
    """
    Vingt par page, cinquante au plus.

    Une taille de page hors bornes est **refusée**, pas ramenée en silence au
    plafond comme le fait le comportement par défaut de DRF. Un client qui
    demande cent éléments et en reçoit cinquante sans le savoir croira la liste
    terminée et perdra la moitié des alertes de son utilisateur.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_page_size(self, request):
        raw = request.query_params.get(self.page_size_query_param)
        if raw is None:
            return self.page_size

        try:
            requested = int(raw)
        except (TypeError, ValueError):
            raise ValidationError(
                {"page_size": "Doit être un entier."},
            ) from None
        if requested < 1 or requested > self.max_page_size:
            raise ValidationError({
                "page_size": f"Doit être compris entre 1 et {self.max_page_size}.",
            })
        return requested

    def get_paginated_response(self, data):
        """
        La collection est nommée, comme partout dans l'espace client.

        `{"notifications": [...]}` plutôt que le `results` de DRF : les autres
        endpoints du client rendent `reservations`, `orders`, `payments`. Un
        nom différent ici obligerait le client de l'API à traiter ce cas à part.
        """
        return Response({
            "notifications": data,
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
        })


class NotificationsPageSerializer(serializers.Serializer):
    """Réponse paginée — déclarée pour que le schéma la décrive."""

    notifications = MyNotificationSerializer(many=True)
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class UnreadCountSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()


class MarkAllReadSerializer(serializers.Serializer):
    marked_read = serializers.IntegerField()


class _CustomerNotificationView(APIView):
    """Socle commun : mêmes voies d'authentification, mêmes compteurs."""

    permission_classes = [IsAuthenticatedCustomer]
    authentication_classes = _CUSTOMER_AUTH
    throttle_classes = _CUSTOMER_THROTTLES

    def get_own_notification(self, request, pk):
        """
        La notification visée, si elle appartient à l'appelant — sinon `None`.

        Le filtre porte les deux conditions ensemble : chercher d'abord puis
        vérifier le destinataire distinguerait « inexistante » de « pas à vous »
        par le temps de réponse comme par le code retourné.
        """
        from notifications.models import Notification

        return (
            Notification.objects
            .filter(pk=pk, recipient_user=request.user)
            .select_related("tenant")
            .first()
        )

    @staticmethod
    def not_found():
        return Response({"detail": "Notification introuvable."}, status=404)


@extend_schema(
    tags=_TAG,
    parameters=[
        OpenApiParameter("unread", bool, description="`true` pour ne garder que les non lues."),
        OpenApiParameter("tenant", str, description="Slug d'une compagnie."),
        OpenApiParameter("category", str, description="Catégorie de préférence de l'événement."),
        OpenApiParameter("priority", str, description="`critical`, `high`, `medium` ou `low`."),
        OpenApiParameter("page", int, description="Numéro de page."),
        OpenApiParameter("page_size", int, description="Éléments par page (1 à 50)."),
    ],
    responses=NotificationsPageSerializer,
)
class MyNotificationsListView(_CustomerNotificationView):
    """
    GET /api/v1/customer/notifications/ — le centre d'alertes du client.

    Toutes compagnies confondues, les plus récentes d'abord.
    """

    pagination_class = NotificationsPagination

    def get(self, request):
        queryset = self.filtered_queryset(request)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            MyNotificationSerializer(page, many=True).data,
        )

    @staticmethod
    def filtered_queryset(request):
        from notifications.models import Notification

        queryset = (
            Notification.objects
            .filter(recipient_user=request.user)
            .select_related("tenant")
            .order_by("-created_at")
        )

        if request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)

        tenant_slug = request.query_params.get("tenant")
        if tenant_slug:
            queryset = queryset.filter(tenant__slug=tenant_slug)

        priority = request.query_params.get("priority")
        if priority:
            queryset = queryset.filter(priority=priority)

        category = request.query_params.get("category")
        if category:
            # La catégorie appartient à l'événement, pas à la ligne : le filtre
            # passe donc par les codes que le catalogue range dans cette
            # catégorie. Une catégorie inconnue rend une liste de codes vide,
            # donc aucune notification — ce qui est la bonne réponse.
            from notifications import catalog

            matching = [
                event.code for event in catalog.all_events()
                if event.category == category
            ]
            queryset = queryset.filter(event_code__in=matching)

        return queryset


@extend_schema(tags=_TAG, responses=UnreadCountSerializer)
class MyNotificationsUnreadCountView(_CustomerNotificationView):
    """
    GET /api/v1/customer/notifications/unread-count/ — la pastille de l'interface.

    Volontairement sans filtre : c'est le total non lu du client, toutes
    compagnies. Un compte filtré n'aurait pas de sens sur une pastille.
    """

    def get(self, request):
        from notifications.models import Notification

        return Response({
            "unread_count": Notification.objects.filter(
                recipient_user=request.user, read_at__isnull=True,
            ).count(),
        })


@extend_schema(tags=_TAG, request=None, responses=MyNotificationSerializer)
class MyNotificationMarkReadView(_CustomerNotificationView):
    """
    POST /api/v1/customer/notifications/<id>/read/ — marquer une alerte lue.

    Idempotent : un second appel ne déplace pas la date. Un client qui rouvre
    son centre d'alertes n'a donc pas à vérifier l'état avant d'appeler, et la
    date conserve le sens de « première consultation ».
    """

    def post(self, request, pk):
        notification = self.get_own_notification(request, pk)
        if notification is None:
            return self.not_found()

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])

        return Response(MyNotificationSerializer(notification).data)


@extend_schema(tags=_TAG, request=None, responses=MyNotificationSerializer)
class MyNotificationAckView(_CustomerNotificationView):
    """
    POST /api/v1/customer/notifications/<id>/ack/ — acquitter explicitement.

    Distinct de la lecture : lire est passif, acquitter est un geste. Acquitter
    vaut donc lecture, l'inverse jamais.

    Refusé sur un événement que le catalogue ne déclare pas `requires_ack` :
    accepter donnerait une trace d'acquittement là où l'interface ne propose
    aucun bouton, et l'on ne saurait plus dire ce que la date signifie.
    """

    def post(self, request, pk):
        from notifications import catalog

        notification = self.get_own_notification(request, pk)
        if notification is None:
            return self.not_found()

        try:
            event = catalog.get_event(notification.event_code)
        except KeyError:
            return Response(
                {"detail": f"Événement {notification.event_code} inconnu du catalogue."},
                status=400,
            )
        if not event.requires_ack:
            return Response(
                {"detail": "Cet événement ne demande pas d'accusé de réception."},
                status=400,
            )

        now = timezone.now()
        updated = []
        if notification.acked_at is None:
            notification.acked_at = now
            updated.append("acked_at")
        if notification.read_at is None:
            notification.read_at = now
            updated.append("read_at")
        if updated:
            notification.save(update_fields=updated)

        return Response(MyNotificationSerializer(notification).data)


@extend_schema(tags=_TAG, request=None, responses=MarkAllReadSerializer)
class MyNotificationsMarkAllReadView(_CustomerNotificationView):
    """
    POST /api/v1/customer/notifications/mark-all-read/ — tout marquer lu.

    Une seule requête SQL, et seules les non lues sont touchées : repasser sur
    les lignes déjà lues écraserait la date de première consultation.
    """

    def post(self, request):
        from notifications.models import Notification

        marked = Notification.objects.filter(
            recipient_user=request.user, read_at__isnull=True,
        ).update(read_at=timezone.now())

        return Response({"marked_read": marked})
