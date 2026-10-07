"""TOUPAC Voyage — ViewSets DRF."""
import uuid
from collections import Counter

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import PriceList, PriceRule
from colis.models import Order as ColisOrder
from iam.permissions import ApiScopedViewSetMixin
from iam.platform_throttles import PlatformKeyRateThrottle
from iam.throttles import ApiKeyAdminRateThrottle, ApiKeyRateThrottle

from .models import (
    CashEntry,
    Controller,
    ControlEvent,
    ControlSession,
    Incident,
    Passenger,
    PassengerAccessLog,
    Reservation,
    Route,
    Schedule,
    SeatMap,
    Trip,
)
from .schema_examples import ALL_EXAMPLES
from .serializers import (
    BatchRequestSerializer,
    BatchResponseSerializer,
    BoardingActionSerializer,
    ControlCloseSerializer,
    ControlEventLookupSerializer,
    ControllerSerializer,
    ControlOpenSerializer,
    ControlSessionConflictSerializer,
    ControlSessionSerializer,
    IncidentDetailSerializer,
    IncidentListSerializer,
    ManifestSerializer,
    PassengerSerializer,
    QrPublicKeySerializer,
    QrPublicKeyUnavailableSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    RouteSerializer,
    ScheduleSerializer,
    SeatMapSerializer,
    TripCreateSerializer,
    TripDetailSerializer,
    TripListSerializer,
)
from .services.event_processor import BatchEventProcessor
from .services.qr_jwt import qr_public_key_pem, sign_ticket_jwt
from .services.seat_map import seat_labels
from .services.trip_summary import build_trip_summary

MAX_BATCH_EVENTS = 100

API_KEY_THROTTLES = [ApiKeyAdminRateThrottle, ApiKeyRateThrottle, PlatformKeyRateThrottle]

_TAG = extend_schema(tags=["Voyage"])
_CRUD_TAGS = {
    "list": _TAG, "retrieve": _TAG, "create": _TAG,
    "update": _TAG, "partial_update": _TAG, "destroy": _TAG,
}


@extend_schema_view(**_CRUD_TAGS)
class RouteViewSet(ApiScopedViewSetMixin, viewsets.ModelViewSet):
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    serializer_class = RouteSerializer
    queryset = Route.objects.none()
    search_fields = ["name", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return (
            Route.objects.filter(tenant=self.request.tenant)
            .select_related("origin_place", "destination_place", "luggage_policy")
            .prefetch_related("stops")
        )


@extend_schema_view(**_CRUD_TAGS)
class ScheduleViewSet(ApiScopedViewSetMixin, viewsets.ModelViewSet):
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    serializer_class = ScheduleSerializer
    queryset = Schedule.objects.none()
    filterset_fields = ["route", "is_active"]

    def get_queryset(self):
        return Schedule.objects.filter(tenant=self.request.tenant).select_related("route", "default_vehicle_type")


@extend_schema_view(**_CRUD_TAGS)
class TripViewSet(ApiScopedViewSetMixin, viewsets.ModelViewSet):
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    queryset = Trip.objects.none()
    filterset_fields = ["status", "route", "departure_date", "vehicle", "driver"]
    search_fields = ["internal_id"]
    ordering_fields = ["departure_date", "scheduled_at", "status"]
    ordering = ["-departure_date"]

    def get_queryset(self):
        return (
            Trip.objects.filter(tenant=self.request.tenant)
            .select_related(
                "route", "route__luggage_policy", "schedule", "vehicle", "driver", "seat_map",
            )
            # `stops__route_stop` : `TripStopSerializer` dérive `is_boarding` et
            # `is_alighting` du `RouteStop` parent — sans ce prefetch, chaque
            # stop déclencherait sa propre requête, N+1 silencieux côté
            # manifest. Un test `assertNumQueries` verrouille le compte.
            .prefetch_related("stops__route_stop")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return TripListSerializer
        if self.action == "retrieve":
            return TripDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return TripCreateSerializer
        return TripDetailSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)

    @extend_schema(request=None, responses={200: ManifestSerializer}, tags=["Voyage"])
    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request, pk=None):
        """GET /voyage/trips/{id}/manifest/ — données complètes pour l'app offline.

        Seul appel que le contrôleur fait avant de perdre le réseau : tout ce
        dont il a besoin pour la durée du voyage doit tenir ici.
        """
        trip = self.get_object()
        reservations = list(trip.reservations.select_related("passenger").all())

        # Un même passager peut porter plusieurs réservations sur un voyage.
        passengers = list({r.passenger_id: r.passenger for r in reservations}.values())

        trip_parcels = list(
            ColisOrder.objects.filter(tenant=trip.tenant, trip=trip)
            .exclude(status=ColisOrder.Status.CANCELLED)
            .select_related("customer")
            .prefetch_related("parcels")
        )

        cash_xof = CashEntry.objects.filter(
            tenant=trip.tenant, session__trip=trip,
        ).aggregate(total=Sum("amount_xof"))["total"] or 0

        counts = Counter(r.status for r in reservations)
        stats = {
            "total_seats": trip.total_seats,
            "booked": counts.get(Reservation.Status.BOOKED, 0),
            "boarded": counts.get(Reservation.Status.BOARDED, 0),
            "no_show": counts.get(Reservation.Status.NO_SHOW, 0),
            "refused": counts.get(Reservation.Status.REFUSED, 0),
            "revenue_xof": sum(
                r.amount_xof for r in reservations
                if r.status != Reservation.Status.CANCELLED
            ),
            "cash_xof": cash_xof,
            "parcels_count": len(trip_parcels),
        }

        data = ManifestSerializer({
            "trip": trip,
            "reservations": reservations,
            "passengers": passengers,
            "seat_occupation": self._build_seat_occupation(trip, reservations),
            "parcels": trip_parcels,
            "pricing": self._build_pricing(trip),
            "active_session": self._active_session_payload(trip),
            "stats": stats,
            "qr_public_key": qr_public_key_pem(),
        }).data
        return Response(data)

    # ─── Helpers du manifest ───

    @staticmethod
    def _build_seat_occupation(trip, reservations):
        """Croise le layout du plan de sièges avec les réservations actives.

        Un siège réservé absent du layout (plan modifié après coup, siège hors
        plan) est ajouté quand même : le contrôleur doit le voir.
        """
        active = {
            r.seat_label: r
            for r in reservations
            if r.status not in (Reservation.Status.CANCELLED, Reservation.Status.REFUSED)
            and r.seat_label
        }

        # Le plan entier, sans troncature : un siège au-delà de `total_seats`
        # qui porte pourtant une réservation doit rester visible du contrôleur.
        layout = (trip.seat_map.layout if trip.seat_map else None) or {}
        labels = seat_labels(layout)

        known = set(labels)
        labels.extend(label for label in active if label not in known)

        occupation = {}
        for label in labels:
            reservation = active.get(label)
            if reservation is None:
                occupation[label] = {"status": "free"}
            else:
                occupation[label] = {
                    "status": reservation.status,
                    "passenger_name": (
                        reservation.passenger.full_name if reservation.passenger else ""
                    ),
                    "reservation_id": str(reservation.id),
                }
        return occupation

    @staticmethod
    def _build_pricing(trip):
        """Tarif de référence pour les ventes à bord : PriceRule, sinon Schedule."""
        rule = PriceRule.objects.filter(
            price_list__tenant=trip.tenant,
            price_list__type=PriceList.Type.VOYAGE,
            price_list__is_active=True,
            route=trip.route,
        ).first()
        if rule:
            default_price = rule.base_amount_xof
        elif trip.schedule:
            default_price = trip.schedule.default_price_xof or 0
        else:
            default_price = 0

        return {
            "default_price_xof": default_price,
            "currency": "XOF",
            "luggage_policy": trip.route.luggage_policy if trip.route else None,
        }

    @staticmethod
    def _active_session_payload(trip):
        """Session de contrôle ouverte sur ce voyage, ou None."""
        session = (
            ControlSession.objects.filter(trip=trip, closed_at__isnull=True)
            .select_related("controller__user")
            .order_by("-opened_at")
            .first()
        )
        if session is None:
            return None
        return {
            "session_id": str(session.id),
            "controller_name": session.controller.user.full_name,
            "device_id": session.device_id,
        }

    @extend_schema(
        request=ControlOpenSerializer,
        responses={
            201: ControlSessionSerializer,
            409: ControlSessionConflictSerializer,
        },
        tags=["Voyage"],
    )
    @action(detail=True, methods=["post"], url_path="control/open")
    def control_open(self, request, pk=None):
        """POST /voyage/trips/{id}/control/open/ — ouvre une session de contrôle.

        Une seule session ouverte par voyage : deux contrôleurs qui synchronisent
        en parallèle produiraient des comptages et des encaissements divergents.
        """
        trip = self.get_object()
        serializer = ControlOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            controller = request.user.controller_profile
        except Controller.DoesNotExist:
            return Response({"detail": "L'utilisateur n'est pas un contrôleur."}, status=403)

        existing_session = (
            ControlSession.objects.filter(trip=trip, closed_at__isnull=True)
            .select_related("controller__user")
            .order_by("-opened_at")
            .first()
        )
        if existing_session:
            return Response({
                "detail": "Une session de contrôle est déjà ouverte pour ce voyage.",
                "existing_session": {
                    "session_id": str(existing_session.id),
                    "controller_name": existing_session.controller.user.full_name,
                    "device_id": existing_session.device_id,
                    "opened_at": existing_session.opened_at.isoformat(),
                },
            }, status=status.HTTP_409_CONFLICT)

        session = ControlSession.objects.create(
            tenant=request.tenant,
            trip=trip,
            controller=controller,
            device_id=serializer.validated_data["device_id"],
            device_info=serializer.validated_data.get("device_info", {}),
            opened_at=timezone.now(),
        )
        if trip.status == Trip.Status.SCHEDULED:
            trip.status = Trip.Status.PREPARING
            trip.save(update_fields=["status", "updated_at"])
        return Response(ControlSessionSerializer(session).data, status=201)

    @extend_schema(
        request=ControlCloseSerializer,
        responses={200: ControlSessionSerializer},
        tags=["Voyage"],
    )
    @action(detail=True, methods=["post"], url_path="control/close")
    def control_close(self, request, pk=None):
        """POST /voyage/trips/{id}/control/close/ — ferme la session de contrôle."""
        trip = self.get_object()
        serializer = ControlCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = ControlSession.objects.filter(
            trip=trip, closed_at__isnull=True
        ).order_by("-opened_at").first()
        if not session:
            return Response({"detail": "Aucune session active."}, status=400)
        # Trois écritures qui doivent tenir ensemble : la session se ferme,
        # son `close_summary` et sa `sync_state` sont posés, et le `Trip.summary`
        # est recalculé. Sans la transaction, un échec sur le second geste
        # laisserait une session fermée avec un résumé périmé sur le trip —
        # exactement le genre d'incohérence qu'on vient diagnostiquer plus tard
        # en se demandant « mais ce voyage a bien eu une clôture, non ? ».
        now = timezone.now()
        with transaction.atomic():
            session.closed_at = now
            session.close_summary = serializer.validated_data["close_summary"]
            session.sync_state = "synced"
            session.save(update_fields=[
                "closed_at", "close_summary", "sync_state", "updated_at",
            ])

            trip_update_fields = ["summary", "updated_at"]
            if trip.status in (
                Trip.Status.IN_TRANSIT, Trip.Status.AT_STOP, Trip.Status.ARRIVING,
            ):
                trip.status = Trip.Status.COMPLETED
                trip.actual_arrival_at = now
                trip_update_fields += ["status", "actual_arrival_at"]
            # Recalculé en entier à chaque fermeture : un trip peut avoir
            # plusieurs sessions successives (contrôleur relevé à l'escale),
            # et `summary` doit refléter l'état courant du voyage, pas la
            # dernière session.
            trip.summary = build_trip_summary(trip)
            trip.save(update_fields=trip_update_fields)
        return Response(ControlSessionSerializer(session).data)


@extend_schema_view(**_CRUD_TAGS)
class SeatMapViewSet(ApiScopedViewSetMixin, viewsets.ModelViewSet):
    """Plans de sièges — full CRUD depuis V1.1.

    Le staff flotte peut créer, modifier, supprimer des plans de sièges
    sans intervention dev. Les contraintes de structure du `layout`
    (grille 2D, labels de sièges uniques, cohérence `total_seats` avec
    le count de cellules de type seat) sont validées côté serializer.

    DELETE refusé (409) si le plan est utilisé par un `Trip` : les
    contrôleurs offline consomment le `layout` via le manifest, et
    supprimer un plan en cours d'usage corromprait leur vue.

    Les apps mobiles RN consomment déjà `seat_map` niché dans
    `ManifestSerializer` — pas d'impact.
    """
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    serializer_class = SeatMapSerializer
    queryset = SeatMap.objects.none()
    filterset_fields = ["vehicle_type", "is_template"]
    search_fields = ["name"]
    ordering_fields = ["name", "total_seats", "created_at"]
    # Templates système en haut (-is_template True trié avant False), puis
    # plans tenant par création récente.
    ordering = ["-is_template", "-created_at"]

    def get_queryset(self):
        # Mélange : plans du tenant courant + templates système (tenant=NULL,
        # is_template=True) visibles par tous. `.distinct()` requis car l'union
        # sur FK optionnelles peut produire des doublons si une ligne satisfait
        # les deux côtés — cf. DECISIONS.md.
        return (
            SeatMap.objects.filter(
                Q(tenant=self.request.tenant)
                | Q(is_template=True, tenant__isnull=True)
            )
            .annotate(usage_count=Count("trips"))
            .distinct()
        )

    def perform_create(self, serializer):
        # Un POST classique crée un plan tenanté. Les templates système ne
        # sont créés que par la migration data — pas depuis l'API.
        serializer.save(tenant=self.request.tenant)

    def _assert_not_template(self, instance, action_label):
        if instance.is_template:
            raise PermissionDenied(
                f"Impossible de {action_label} un template système. "
                f"Utilisez 'cloner' pour créer une copie modifiable."
            )

    def perform_update(self, serializer):
        self._assert_not_template(serializer.instance, "modifier")
        super().perform_update(serializer)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self._assert_not_template(instance, "supprimer")
        trip_count = Trip.objects.filter(seat_map=instance).count()
        if trip_count > 0:
            plural = "s" if trip_count > 1 else ""
            return Response(
                {
                    "detail": (
                        f"Impossible de supprimer : ce plan est utilisé par "
                        f"{trip_count} voyage{plural}."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        # Vehicle.default_seat_map FK = on_delete=SET_NULL (migration fleet
        # 0003) — pas de guard supplémentaire : les véhicules survivent avec
        # default_seat_map=NULL.
        return super().destroy(request, *args, **kwargs)

    @extend_schema(request=None, responses={201: SeatMapSerializer}, tags=["Voyage"])
    @action(detail=True, methods=["post"], url_path="clone")
    def clone(self, request, pk=None):
        """POST /voyage/seat-maps/{id}/clone/ — copie un template ou un plan.

        Autorisé pour les templates système (quel que soit le tenant) et pour
        les plans du tenant courant. Interdit (403) pour les plans d'un autre
        tenant — bien que `get_queryset()` ne les expose pas, un ID forgé
        serait refusé ici.

        Payload optionnel : `{"name": "..."}`. Sinon fallback `Copie de <nom>`.
        """
        source = self.get_object()
        tenant = request.tenant
        if not source.is_template and source.tenant_id != tenant.id:
            raise PermissionDenied(
                "Impossible de cloner un plan d'un autre tenant."
            )
        new_name = (request.data or {}).get("name") or f"Copie de {source.name}"
        clone_instance = SeatMap.objects.create(
            tenant=tenant,
            name=new_name,
            vehicle_type=source.vehicle_type,
            layout=source.layout,
            total_seats=source.total_seats,
            is_template=False,
        )
        # Ré-annoter pour que `usage_count` soit cohérent dans la réponse.
        clone_instance = (
            SeatMap.objects.annotate(usage_count=Count("trips"))
            .get(pk=clone_instance.pk)
        )
        serializer = self.get_serializer(clone_instance)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(list=_TAG, retrieve=_TAG)
class IncidentViewSet(ApiScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Liste et détail des incidents voyage — lecture seule V1.

    Les incidents sont créés par les contrôleurs via l'app mobile et remontent
    par le batch sync (/control-events/batch/). Le backoffice web les consulte
    pour les décisions managériales (résolution, escalade). Les actions
    d'écriture (résolution, réponse) sont prévues V1.2+.
    """
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    queryset = Incident.objects.none()
    filterset_fields = ["status", "severity", "type", "trip", "reporter", "dispatcher_notified"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "severity", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Incident.objects.filter(tenant=self.request.tenant)
            .select_related("trip__route", "reporter", "session")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return IncidentListSerializer
        return IncidentDetailSerializer


_BOARDING_ACTION_SCHEMA = extend_schema(
    request=BoardingActionSerializer,
    responses={200: ReservationSerializer},
    tags=["Voyage"],
)


@extend_schema_view(**_CRUD_TAGS)
class ReservationViewSet(ApiScopedViewSetMixin, viewsets.ModelViewSet):
    api_scope_domain = "voyage"
    throttle_classes = API_KEY_THROTTLES
    queryset = Reservation.objects.none()
    filterset_fields = ["trip", "status", "passenger", "payment_method"]

    def get_queryset(self):
        return Reservation.objects.filter(tenant=self.request.tenant).select_related("trip", "passenger")

    def get_serializer_class(self):
        if self.action == "create":
            return ReservationCreateSerializer
        return ReservationSerializer

    def create(self, request, *args, **kwargs):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = serializer.save(tenant=request.tenant, created_by=request.user)
        reservation.qr_code_jwt = sign_ticket_jwt(reservation)
        reservation.save(update_fields=["qr_code_jwt"])
        return Response(ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED)

    @_BOARDING_ACTION_SCHEMA
    @action(detail=True, methods=["post"])
    def board(self, request, pk=None):
        """POST /voyage/reservations/{id}/board/"""
        reservation = self.get_object()
        if reservation.status not in ("booked", "checked_in"):
            return Response({"detail": f"Impossible d'embarquer : statut={reservation.status}"}, status=400)
        serializer = BoardingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation.status = "boarded"
        reservation.boarded_at = timezone.now()
        reservation.boarding_method = serializer.validated_data.get("boarding_method", "qr_scan")
        reservation.save(update_fields=["status", "boarded_at", "boarding_method", "updated_at"])
        trip = reservation.trip
        if trip.status == Trip.Status.PREPARING:
            trip.status = Trip.Status.BOARDING
            trip.save(update_fields=["status", "updated_at"])
        return Response(ReservationSerializer(reservation).data)

    @_BOARDING_ACTION_SCHEMA
    @action(detail=True, methods=["post"])
    def refuse(self, request, pk=None):
        """POST /voyage/reservations/{id}/refuse/"""
        reservation = self.get_object()
        serializer = BoardingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation.status = "refused"
        reservation.refusal_reason = serializer.validated_data.get("refusal_reason", "")
        reservation.save(update_fields=["status", "refusal_reason", "updated_at"])
        return Response(ReservationSerializer(reservation).data)

    @_BOARDING_ACTION_SCHEMA
    @action(detail=True, methods=["post"], url_path="special-case")
    def special_case(self, request, pk=None):
        """POST /voyage/reservations/{id}/special-case/"""
        reservation = self.get_object()
        serializer = BoardingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation.status = "boarded"
        reservation.boarded_at = timezone.now()
        reservation.boarding_method = "manual"
        reservation.special_case_reason = serializer.validated_data.get("special_case_reason", "")
        reservation.save()
        return Response(ReservationSerializer(reservation).data)


@extend_schema_view(**_CRUD_TAGS)
class PassengerViewSet(viewsets.ModelViewSet):
    serializer_class = PassengerSerializer
    queryset = Passenger.objects.none()
    search_fields = ["first_name", "last_name", "phone"]

    def get_queryset(self):
        return Passenger.objects.filter(tenant=self.request.tenant)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        include_id_card = request.query_params.get("include_id_card", "").lower() == "true"
        serializer = PassengerSerializer(instance, include_id_card=include_id_card)
        if include_id_card:
            PassengerAccessLog.objects.create(
                tenant=request.tenant,
                passenger=instance,
                user=request.user if request.user.is_authenticated else None,
                context=PassengerAccessLog.Context.ADMIN_VIEW,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        return Response(serializer.data)


@extend_schema_view(list=_TAG, retrieve=_TAG)
class ControllerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ControllerSerializer
    queryset = Controller.objects.none()
    search_fields = ["matricule", "user__first_name", "user__last_name"]

    def get_queryset(self):
        return Controller.objects.filter(tenant=self.request.tenant).select_related("user")


@extend_schema(
    tags=["Voyage"],
    request=BatchRequestSerializer,
    responses={200: BatchResponseSerializer},
    # Dix exemples en entrée, un par `event_type`, plus deux verdicts en
    # sortie. Les littéraux vivent dans `schema_examples.py` : la vue n'a
    # pas à porter deux cents lignes de JSON, et un test de non-régression
    # relit le même module pour vérifier qu'un exemple reste aligné avec
    # son handler.
    examples=ALL_EXAMPLES,
)
class ControlEventBatchView(APIView):
    """
    POST /api/v1/voyage/control-events/batch/

    Endpoint critique du mode offline : l'app contrôleur rejoue ici les events
    accumulés sans réseau. Chaque event reçoit son verdict individuel — un
    event rejeté ne fait pas échouer le batch.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = "batch_sync"

    def post(self, request):
        events_data = request.data.get("events", [])
        if not isinstance(events_data, list) or len(events_data) == 0:
            return Response(
                {"detail": "Le champ 'events' est requis (liste non vide)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(events_data) > MAX_BATCH_EVENTS:
            return Response(
                {"detail": f"Maximum {MAX_BATCH_EVENTS} events par batch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            controller = request.user.controller_profile
        except Controller.DoesNotExist:
            return Response(
                {"detail": "Utilisateur non contrôleur."},
                status=status.HTTP_403_FORBIDDEN,
            )

        session, error = self._resolve_session(request, controller)
        if error is not None:
            return error

        # La session porte le tenant faisant autorité — le middleware peut ne
        # pas l'avoir résolu (super-admin sans tenant, par exemple).
        processor = BatchEventProcessor(
            session=session, tenant=request.tenant or session.tenant, user=request.user
        )
        results = processor.process_batch(events_data)

        return Response({
            "session_id": str(session.id),
            "processed": len(results),
            "results": results,
        })

    @staticmethod
    def _resolve_session(request, controller):
        """
        Détermine la session à laquelle rattacher le batch.

        Retourne (session, None) ou (None, Response d'erreur).

        Un `session_id` explicite est accepté même sur une session fermée :
        c'est tout l'intérêt du champ. Sans lui, un contrôleur qui ferme la
        session A, ouvre la B, puis resynchronise tardivement les events
        accumulés dans A les verrait atterrir dans B.
        """
        raw_session_id = request.data.get("session_id")

        if raw_session_id in (None, ""):
            session = (
                ControlSession.objects
                .filter(controller=controller, closed_at__isnull=True)
                .order_by("-opened_at")
                .first()
            )
            if session is None:
                return None, Response(
                    {"detail": "Aucune session de contrôle active."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return session, None

        try:
            session_id = uuid.UUID(str(raw_session_id))
        except (TypeError, ValueError):
            return None, Response(
                {"detail": "session_id invalide (UUID attendu)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session = ControlSession.objects.filter(id=session_id).first()
        if session is None:
            return None, Response(
                {"detail": "Session introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if session.controller_id != controller.id:
            return None, Response(
                {"detail": "Cette session n'appartient pas au contrôleur authentifié."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return session, None


@extend_schema(
    tags=["Voyage"],
    request=None,
    responses={200: QrPublicKeySerializer, 503: QrPublicKeyUnavailableSerializer},
)
class QrPublicKeyView(APIView):
    """
    GET /api/v1/voyage/qr-public-key/

    Clé publique RS256 de vérification des QR de billets — pas un secret, donc
    pas d'authentification. Endpoint dédié distinct du manifest pour que l'app
    mobile puisse la refetch seule en cas de rotation, sans retélécharger un
    manifest complet.
    """
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        public_key = qr_public_key_pem()
        if public_key is None:
            return Response(
                {"detail": "QR key not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"public_key_pem": public_key})


_CONTROL_EVENT_LOOKUP_ERROR = inline_serializer(
    name="ControlEventLookupError",
    fields={"detail": serializers.CharField()},
)


@extend_schema(
    tags=["Voyage"],
    request=None,
    responses={
        200: ControlEventLookupSerializer,
        400: OpenApiResponse(response=_CONTROL_EVENT_LOOKUP_ERROR),
        403: OpenApiResponse(response=_CONTROL_EVENT_LOOKUP_ERROR),
        404: OpenApiResponse(response=_CONTROL_EVENT_LOOKUP_ERROR),
    },
)
class ControlEventLookupView(APIView):
    """
    GET /api/v1/voyage/control-events/{client_uuid}/

    Lookup direct par `client_uuid` pour la réconciliation mobile après
    crash/timeout : le mobile sait si son event a atteint le serveur, et
    peut rejouer en confiance quand la réponse est 404 (jamais vu).

    Scope strict contrôleur : un `client_uuid` d'un autre contrôleur du même
    tenant renvoie 404 — jamais 403. Doctrine DECISIONS.md « une ressource
    nominative qui ne vous appartient pas répond 404, pas 403 ».
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = API_KEY_THROTTLES

    def get(self, request, client_uuid):
        # Garde-fou défensif : le path converter `<uuid:...>` filtre déjà en
        # amont, mais un appel programmatique de la vue avec un str passerait
        # au-delà. On garde ce try/except pour cette raison.
        try:
            parsed_uuid = uuid.UUID(str(client_uuid))
        except (TypeError, ValueError):
            return Response(
                {"detail": "client_uuid invalide (UUID attendu)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            controller = request.user.controller_profile
        except Controller.DoesNotExist:
            return Response(
                {"detail": "Utilisateur non contrôleur."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # `select_related("session")` : le serializer lit `session.id` via
        # `source="session.id"`. Sans ce JOIN, chaque réponse déclencherait
        # une 2e query. Un seul event concerné, zéro N+1 à craindre.
        event = (
            ControlEvent.objects
            .filter(
                tenant=request.tenant,
                client_uuid=parsed_uuid,
                session__controller=controller,
            )
            .select_related("session")
            .first()
        )
        if event is None:
            return Response(
                {"detail": "Événement introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ControlEventLookupSerializer(event).data)
