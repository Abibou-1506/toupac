"""TOUPAC Tracking — ViewSets et vues DRF."""
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from fleet.models import Vehicle
from iam.permissions import ApiScopedViewSetMixin
from iam.platform_throttles import PlatformKeyRateThrottle
from iam.throttles import ApiKeyAdminRateThrottle, ApiKeyRateThrottle

from .models import Geofence, Position, TrackingLink
from .serializers import (
    GeofenceSerializer,
    PositionBatchSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PublicTrackingSerializer,
    TrackingLinkCreateSerializer,
    TrackingLinkSerializer,
)

API_KEY_THROTTLES = [ApiKeyAdminRateThrottle, ApiKeyRateThrottle, PlatformKeyRateThrottle]

_TAG = extend_schema(tags=["Tracking"])


@extend_schema_view(list=_TAG, retrieve=_TAG, create=_TAG, batch=_TAG, vehicle_latest=_TAG)
class PositionViewSet(
    ApiScopedViewSetMixin,
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    # Les positions arrivent par le boîtier télématique, pas par l'API
    # publique : en pratique seul `tracking:read` est accordé aux partenaires,
    # l'écriture reste possible mais demande `tracking:write`.
    api_scope_domain = "tracking"
    throttle_classes = API_KEY_THROTTLES
    queryset = Position.objects.none()
    filterset_fields = ["vehicle", "source"]
    ordering = ["-recorded_at"]

    def get_queryset(self):
        return Position.objects.filter(tenant=self.request.tenant).select_related("vehicle", "driver")

    def get_serializer_class(self):
        if self.action == "create":
            return PositionCreateSerializer
        return PositionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        position = serializer.save()
        return Response(PositionSerializer(position).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="batch")
    def batch(self, request):
        """POST /tracking/positions/batch/ — batch de positions (app chauffeur)."""
        serializer = PositionBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        positions_data = serializer.validated_data["positions"]

        from django.contrib.gis.geos import Point
        vehicle_id = positions_data[0]["vehicle_id"]
        vehicle = Vehicle.objects.get(id=vehicle_id, tenant=request.tenant)

        objs = []
        for p in positions_data:
            objs.append(Position(
                tenant=request.tenant,
                vehicle=vehicle,
                driver=getattr(request.user, "driver_profile", None),
                location=Point(p["lng"], p["lat"], srid=4326),
                speed_kmh=p.get("speed_kmh"),
                heading=p.get("heading"),
                accuracy_m=p.get("accuracy_m"),
                altitude_m=p.get("altitude_m"),
                source=p.get("source", "driver_app"),
                recorded_at=p["recorded_at"],
            ))
        created = Position.objects.bulk_create(objs)

        if objs:
            last = objs[-1]
            Vehicle.objects.filter(id=vehicle_id).update(location=last.location)

        return Response({"created": len(created)}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path=r"vehicle/(?P<vehicle_id>[^/.]+)/latest")
    def vehicle_latest(self, request, vehicle_id=None):
        """GET /tracking/positions/vehicle/{vehicle_id}/latest/"""
        position = Position.objects.filter(
            tenant=request.tenant, vehicle_id=vehicle_id,
        ).first()
        if not position:
            return Response({"detail": "Aucune position."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PositionSerializer(position).data)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class GeofenceViewSet(viewsets.ModelViewSet):
    serializer_class = GeofenceSerializer
    queryset = Geofence.objects.none()
    filterset_fields = ["type", "is_active"]

    def get_queryset(self):
        return Geofence.objects.filter(tenant=self.request.tenant)


@extend_schema_view(list=_TAG, create=_TAG)
class TrackingLinkViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = TrackingLink.objects.none()

    def get_queryset(self):
        return TrackingLink.objects.filter(tenant=self.request.tenant)

    def get_serializer_class(self):
        if self.action == "create":
            return TrackingLinkCreateSerializer
        return TrackingLinkSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = serializer.save()
        return Response(TrackingLinkSerializer(link).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Tracking"], responses=PublicTrackingSerializer)
class PublicTrackingView(APIView):
    """GET /api/v1/tracking/links/{token}/ — suivi public sans auth."""
    permission_classes = []
    authentication_classes = []

    def get(self, request, token):
        link = TrackingLink.objects.filter(
            token=token, expires_at__gt=timezone.now(),
        ).first()
        if not link:
            return Response({"detail": "Lien invalide ou expiré."}, status=status.HTTP_404_NOT_FOUND)

        last_position = None
        status_val = ""
        route_name = ""
        tracking_number = ""

        if link.resource_type == TrackingLink.ResourceType.TRIP:
            from voyage.models import Trip
            trip = Trip.objects.filter(id=link.resource_id).first()
            if trip:
                status_val = trip.status
                route_name = trip.route.name if trip.route else ""
                if trip.vehicle_id:
                    pos = Position.objects.filter(vehicle_id=trip.vehicle_id).first()
                    if pos:
                        last_position = {
                            "lat": pos.location.y, "lng": pos.location.x,
                            "recorded_at": pos.recorded_at.isoformat(),
                        }
        elif link.resource_type == TrackingLink.ResourceType.ORDER:
            from colis.models import Order
            order = Order.objects.filter(id=link.resource_id).first()
            if order:
                status_val = order.status
                parcel = order.parcels.first()
                tracking_number = parcel.tracking_number if parcel else ""

        data = {
            "resource_type": link.resource_type,
            "resource_id": str(link.resource_id),
            "status": status_val,
            "last_position": last_position,
            "route_name": route_name,
            "tracking_number": tracking_number,
        }
        return Response(PublicTrackingSerializer(data).data)
