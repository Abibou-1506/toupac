"""TOUPAC Voyage — ViewSets DRF."""
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import (
    Route, Schedule, Trip, TripStop, Passenger, Reservation, Controller,
    ControlSession, PassengerAccessLog,
)
from .serializers import (
    RouteSerializer, ScheduleSerializer, TripListSerializer, TripDetailSerializer,
    TripCreateSerializer, PassengerSerializer, ReservationSerializer,
    ReservationCreateSerializer, ManifestSerializer, BoardingActionSerializer,
    ControllerSerializer, ControlSessionSerializer, ControlOpenSerializer,
    ControlCloseSerializer,
)
from .services.event_processor import BatchEventProcessor
from .services.qr_jwt import sign_ticket_jwt

MAX_BATCH_EVENTS = 100

_TAG = extend_schema(tags=["Voyage"])
_CRUD_TAGS = dict(list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG)


@extend_schema_view(**_CRUD_TAGS)
class RouteViewSet(viewsets.ModelViewSet):
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
class ScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ScheduleSerializer
    queryset = Schedule.objects.none()
    filterset_fields = ["route", "is_active"]

    def get_queryset(self):
        return Schedule.objects.filter(tenant=self.request.tenant).select_related("route", "default_vehicle_type")


@extend_schema_view(**_CRUD_TAGS, manifest=_TAG, control_open=_TAG, control_close=_TAG)
class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.none()
    filterset_fields = ["status", "route", "departure_date", "vehicle", "driver"]
    search_fields = ["internal_id"]
    ordering_fields = ["departure_date", "scheduled_at", "status"]
    ordering = ["-departure_date"]

    def get_queryset(self):
        return (
            Trip.objects.filter(tenant=self.request.tenant)
            .select_related("route", "schedule", "vehicle", "driver", "seat_map")
            .prefetch_related("stops")
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

    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request, pk=None):
        """GET /voyage/trips/{id}/manifest/ — données complètes pour l'app offline."""
        trip = self.get_object()
        reservations = trip.reservations.select_related("passenger").all()
        passengers = [r.passenger for r in reservations]
        stats = {
            "total_seats": trip.total_seats,
            "booked": reservations.filter(status="booked").count(),
            "boarded": reservations.filter(status="boarded").count(),
            "no_show": reservations.filter(status="no_show").count(),
            "revenue_xof": sum(r.amount_xof for r in reservations if r.status != "cancelled"),
        }
        data = ManifestSerializer({
            "trip": trip,
            "reservations": reservations,
            "passengers": passengers,
            "stats": stats,
        }).data
        return Response(data)

    @action(detail=True, methods=["post"], url_path="control/open")
    def control_open(self, request, pk=None):
        """POST /voyage/trips/{id}/control/open/ — ouvre une session de contrôle."""
        trip = self.get_object()
        serializer = ControlOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            controller = request.user.controller_profile
        except Controller.DoesNotExist:
            return Response({"detail": "L'utilisateur n'est pas un contrôleur."}, status=403)
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
        session.closed_at = timezone.now()
        session.close_summary = serializer.validated_data["close_summary"]
        session.sync_state = "synced"
        session.save()
        if trip.status in (Trip.Status.IN_TRANSIT, Trip.Status.AT_STOP, Trip.Status.ARRIVING):
            trip.status = Trip.Status.COMPLETED
            trip.actual_arrival_at = timezone.now()
            trip.save(update_fields=["status", "actual_arrival_at", "updated_at"])
        return Response(ControlSessionSerializer(session).data)


@extend_schema_view(**_CRUD_TAGS, board=_TAG, refuse=_TAG, special_case=_TAG)
class ReservationViewSet(viewsets.ModelViewSet):
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
    request=inline_serializer("ControlEventBatchRequest", {
        "events": serializers.ListField(child=serializers.DictField()),
    }),
    responses=inline_serializer("ControlEventBatchResponse", {
        "session_id": serializers.CharField(required=False),
        "processed": serializers.IntegerField(required=False),
        "results": serializers.ListField(child=serializers.DictField(), required=False),
        "detail": serializers.CharField(required=False),
    }),
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

        session = ControlSession.objects.filter(
            controller=controller, closed_at__isnull=True
        ).order_by("-opened_at").first()
        if not session:
            return Response(
                {"detail": "Aucune session de contrôle active."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
