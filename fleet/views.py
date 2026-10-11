"""TOUPAC Fleet — ViewSets DRF."""
import io
import os
import zipfile
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .filters import DriverFilterSet
from .models import (
    Driver,
    DriverDocument,
    DriverHRNote,
    Fleet,
    Vehicle,
    VehicleMaintenance,
    VehicleType,
)
from .serializers import (
    DriverCreateSerializer,
    DriverDetailSerializer,
    DriverDocumentSerializer,
    DriverHRNoteSerializer,
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


class _SuspendDriverInputSerializer(drf_serializers.Serializer):
    reason = drf_serializers.CharField(min_length=10, required=True)


class _ReactivateDriverInputSerializer(drf_serializers.Serializer):
    reason = drf_serializers.CharField(required=False, allow_blank=True)


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
    available=_TAG,
)
class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.none()
    # FilterSet dédié (dette V1.1 Vague 4) — expose ``license_classes`` CSV
    # overlap et ``is_assigned`` true/false en plus de ``status``.
    filterset_class = DriverFilterSet
    search_fields = ["user__first_name", "user__last_name", "license_number"]

    def get_queryset(self):
        return (
            Driver.objects.filter(tenant=self.request.tenant)
            .select_related("user")
            .annotate(documents_count=Count("documents"))
        )

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

    @action(
        detail=True,
        methods=["post"],
        url_path="photo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_photo(self, request, pk=None):
        """POST /fleet/drivers/{id}/photo/ — upload multipart (5MB max,
        jpeg/png/webp)."""
        driver = self.get_object()
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
        driver.photo = photo
        driver.save(update_fields=["photo", "updated_at"])
        return Response(
            DriverDetailSerializer(driver, context={"request": request}).data,
        )

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        """Suspend driver. Reason obligatoire (≥10 chars). Crée une HRNote
        atomiquement avec ``kind='suspension'``."""
        driver = self.get_object()
        serializer = _SuspendDriverInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]
        user = request.user if request.user.is_authenticated else None
        with transaction.atomic():
            driver.status = Driver.Status.OFF_DUTY
            driver.save(update_fields=["status", "updated_at"])
            DriverHRNote.objects.create(
                tenant=driver.tenant,
                driver=driver,
                kind=DriverHRNote.Kind.SUSPENSION,
                text=reason,
                by=user,
            )
        # Rechargement avec annotation pour sérialiser proprement
        driver = self.get_queryset().get(pk=driver.pk)
        return Response(
            DriverDetailSerializer(driver, context={"request": request}).data,
        )

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        """Réactive un chauffeur suspendu. Motif optionnel. Crée une HRNote
        avec ``kind='reactivation'``."""
        driver = self.get_object()
        serializer = _ReactivateDriverInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason") or "Réactivation"
        user = request.user if request.user.is_authenticated else None
        with transaction.atomic():
            driver.status = Driver.Status.AVAILABLE
            driver.save(update_fields=["status", "updated_at"])
            DriverHRNote.objects.create(
                tenant=driver.tenant,
                driver=driver,
                kind=DriverHRNote.Kind.REACTIVATION,
                text=reason,
                by=user,
            )
        driver = self.get_queryset().get(pk=driver.pk)
        return Response(
            DriverDetailSerializer(driver, context={"request": request}).data,
        )

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request, pk=None):
        """GET /fleet/drivers/{id}/stats/ — statistiques page détail DS.

        Retourne ``trips_this_month``, ``trips_this_year``,
        ``trips_last_month``, ``average_rating`` et ``ponctuality_pct``.

        **Dette V1.1 (dues à l'absence de champs sources)** :
        - ``average_rating`` → null (pas de champ ``rating`` sur Reservation).
        - ``ponctuality_pct`` → null (nécessite ``actual_departure_at`` vs
          ``scheduled_at`` normalisés — à poser en V1.1).
        """
        from voyage.models import Trip

        driver = self.get_object()
        now = timezone.now()
        trips_this_month = Trip.objects.filter(
            driver=driver,
            scheduled_at__year=now.year,
            scheduled_at__month=now.month,
        ).count()
        trips_this_year = Trip.objects.filter(
            driver=driver, scheduled_at__year=now.year,
        ).count()
        prev_month = now.replace(day=1) - timedelta(days=1)
        trips_last_month = Trip.objects.filter(
            driver=driver,
            scheduled_at__year=prev_month.year,
            scheduled_at__month=prev_month.month,
        ).count()
        return Response({
            "trips_this_month": trips_this_month,
            "trips_this_year": trips_this_year,
            "trips_last_month": trips_last_month,
            "average_rating": None,
            "ponctuality_pct": None,
        })


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class DriverHRNoteViewSet(viewsets.ModelViewSet):
    """CRUD des notes RH chauffeur. Delete bloqué pour non-superadmin
    (audit immuable)."""

    serializer_class = DriverHRNoteSerializer
    queryset = DriverHRNote.objects.none()
    filterset_fields = ["driver", "kind"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            DriverHRNote.objects.filter(tenant=self.request.tenant)
            .select_related("driver", "by")
        )

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(tenant=self.request.tenant, by=user)

    def perform_destroy(self, instance):
        if not getattr(self.request.user, "is_superuser", False):
            raise PermissionDenied(
                "Les notes RH sont immuables (audit) — suppression réservée au superadmin.",
            )
        instance.delete()


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class DriverDocumentViewSet(viewsets.ModelViewSet):
    """CRUD des documents chauffeur (permis scanné, visite médicale…)."""

    serializer_class = DriverDocumentSerializer
    queryset = DriverDocument.objects.none()
    filterset_fields = ["driver", "type"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return (
            DriverDocument.objects.filter(tenant=self.request.tenant)
            .select_related("driver")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


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
