"""TOUPAC Fleet — ViewSets DRF."""
import io
import os
import zipfile

from django.db.models import Count
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import Driver, Fleet, Vehicle, VehicleMaintenance, VehicleType
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
    VehicleMaintenanceSerializer,
    VehicleTypeSerializer,
)

MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

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

    @action(
        detail=True,
        methods=["post"],
        url_path="photo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_photo(self, request, pk=None):
        """POST /fleet/vehicles/{id}/photo/ — upload multipart (5MB max,
        jpeg/png/webp)."""
        vehicle = self.get_object()
        photo = request.FILES.get("photo")
        if photo is None:
            return Response(
                {"detail": "Champ 'photo' requis (multipart)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if photo.size > MAX_PHOTO_SIZE:
            return Response(
                {"detail": "Fichier trop volumineux (max 5 MB)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if photo.content_type not in ALLOWED_PHOTO_CONTENT_TYPES:
            return Response(
                {"detail": "Type MIME non supporté (jpeg/png/webp uniquement)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vehicle.photo = photo
        vehicle.save(update_fields=["photo", "updated_at"])
        return Response(
            VehicleDetailSerializer(vehicle, context={"request": request}).data,
        )

    @action(detail=True, methods=["get"], url_path="documents/export")
    def export_documents_zip(self, request, pk=None):
        """GET /fleet/vehicles/{id}/documents/export/ — ZIP de tous les
        fichiers (FileField) des documents du véhicule. ZIP vide si aucun
        document avec fichier local."""
        vehicle = self.get_object()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc in vehicle.documents.all():
                if not doc.file:
                    continue
                basename = os.path.basename(doc.file.name)
                _, ext = os.path.splitext(basename)
                label = doc.document_number or str(doc.id)
                arcname = f"{doc.get_type_display()}_{label}{ext}"
                try:
                    zf.write(doc.file.path, arcname=arcname)
                except (NotImplementedError, ValueError):
                    doc.file.open("rb")
                    try:
                        zf.writestr(arcname, doc.file.read())
                    finally:
                        doc.file.close()
        resp = HttpResponse(
            buf.getvalue(), content_type="application/zip",
        )
        resp["Content-Disposition"] = (
            f'attachment; filename="vehicle_{vehicle.plate_number}_documents.zip"'
        )
        return resp


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class VehicleMaintenanceViewSet(viewsets.ModelViewSet):
    """CRUD des interventions de maintenance d'un véhicule."""

    serializer_class = VehicleMaintenanceSerializer
    queryset = VehicleMaintenance.objects.none()
    filterset_fields = ["vehicle", "type"]
    ordering_fields = ["at", "odometer_km", "cost_xof"]
    ordering = ["-at", "-created_at"]

    def get_queryset(self):
        return (
            VehicleMaintenance.objects.filter(tenant=self.request.tenant)
            .select_related("vehicle", "created_by")
        )

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(tenant=self.request.tenant, created_by=user)


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
