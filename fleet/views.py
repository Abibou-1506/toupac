"""TOUPAC Fleet — ViewSets DRF."""
from django.db.models import Count
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Driver, Fleet, Vehicle, VehicleType
from .serializers import (
    DriverCreateSerializer,
    DriverDetailSerializer,
    DriverListSerializer,
    FleetCreateSerializer,
    FleetSerializer,
    VehicleCreateSerializer,
    VehicleDetailSerializer,
    VehicleDocumentCreateSerializer,
    VehicleDocumentSerializer,
    VehicleListSerializer,
    VehicleTypeSerializer,
)

_TAG = extend_schema(tags=["Fleet"])


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class VehicleTypeViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleTypeSerializer
    queryset = VehicleType.objects.none()
    search_fields = ["name"]

    def get_queryset(self):
        return VehicleType.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
    documents=_TAG, available=_TAG,
)
class VehicleViewSet(viewsets.ModelViewSet):
    queryset = Vehicle.objects.none()
    filterset_fields = ["status", "vehicle_type"]
    search_fields = ["plate_number", "make", "model_name", "vin"]
    ordering = ["plate_number"]

    def get_queryset(self):
        return Vehicle.objects.filter(tenant=self.request.tenant).select_related("vehicle_type")

    def get_serializer_class(self):
        if self.action == "list":
            return VehicleListSerializer
        if self.action == "retrieve":
            return VehicleDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return VehicleCreateSerializer
        return VehicleDetailSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            docs = vehicle.documents.all()
            return Response(VehicleDocumentSerializer(docs, many=True).data)

        serializer = VehicleDocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(tenant=request.tenant, vehicle=vehicle)
        return Response(VehicleDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="available")
    def available(self, request):
        """GET /fleet/vehicles/available/ — véhicules disponibles."""
        vehicles = self.get_queryset().filter(status="available")
        serializer = VehicleListSerializer(vehicles, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
    available=_TAG,
)
class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.none()
    filterset_fields = ["status"]
    search_fields = ["user__first_name", "user__last_name", "license_number"]

    def get_queryset(self):
        return Driver.objects.filter(tenant=self.request.tenant).select_related("user")

    def get_serializer_class(self):
        if self.action == "list":
            return DriverListSerializer
        if self.action == "retrieve":
            return DriverDetailSerializer
        if self.action == "create":
            return DriverCreateSerializer
        return DriverDetailSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="available")
    def available(self, request):
        """GET /fleet/drivers/available/ — chauffeurs disponibles."""
        drivers = self.get_queryset().filter(status="available")
        serializer = DriverListSerializer(drivers, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class FleetViewSet(viewsets.ModelViewSet):
    queryset = Fleet.objects.none()
    search_fields = ["name", "zone"]

    def get_queryset(self):
        return (
            Fleet.objects.filter(tenant=self.request.tenant)
            .select_related("manager")
            .annotate(vehicle_count=Count("vehicles"))
        )

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return FleetCreateSerializer
        return FleetSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
