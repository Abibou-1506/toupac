"""TOUPAC Fleet — Serializers DRF."""
from django.contrib.gis.geos import Point
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from iam.models import User
from voyage.models import LuggagePolicy, SeatMap

from .models import (
    Driver,
    DriverDocument,
    DriverHRNote,
    Fleet,
    FleetVehicle,
    Vehicle,
    VehicleDocument,
    VehicleMaintenance,
    VehicleType,
)


class PointFieldSerializer(serializers.Field):
    """Sérialise/désérialise un PointField GIS en {"lat": ..., "lng": ...}."""

    def to_representation(self, value):
        if value is None:
            return None
        return {"lat": value.y, "lng": value.x}

    def to_internal_value(self, data):
        try:
            return Point(float(data["lng"]), float(data["lat"]), srid=4326)
        except (KeyError, TypeError, ValueError) as exc:
            raise serializers.ValidationError('Attendu : {"lat": float, "lng": float}') from exc


class LuggagePolicyMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = LuggagePolicy
        fields = ["id", "name"]


class SeatMapMiniSerializer(serializers.ModelSerializer):
    """Shape compact consommé par le frontend ``SeatMapTemplateRef``.

    Exposé partout où un plan de sièges doit être présenté en nested read
    (``VehicleType.default_seat_map``, ``Vehicle.default_seat_map``…) sans
    tirer tout le plan complet.
    """

    class Meta:
        model = SeatMap
        fields = ["id", "name", "total_seats", "is_template"]


class VehicleTypeSerializer(serializers.ModelSerializer):
    # Alias plat pour les mockups DS qui attendent `seats` au lieu de
    # `default_capacity`. Les deux restent exposés en lecture.
    seats = serializers.IntegerField(source="default_capacity", required=False)
    default_luggage_policy = LuggagePolicyMiniSerializer(read_only=True)
    default_luggage_policy_id = serializers.PrimaryKeyRelatedField(
        source="default_luggage_policy",
        queryset=LuggagePolicy.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    default_seat_map = SeatMapMiniSerializer(read_only=True)
    default_seat_map_id = serializers.PrimaryKeyRelatedField(
        source="default_seat_map",
        queryset=SeatMap.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = VehicleType
        fields = [
            "id", "name", "short", "category", "description",
            "default_capacity", "seats", "fuel_type", "permit_required",
            "length_m", "width_m", "height_m", "ptac_kg", "hold_m3",
            "wheelbase_mm", "axles_count",
            "default_luggage_policy", "default_luggage_policy_id",
            "default_seat_map", "default_seat_map_id",
        ]


class VehicleTypeMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ["id", "name", "short"]


class VehicleDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleDocument
        fields = "__all__"


class VehicleDocumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleDocument
        fields = ["type", "document_number", "issue_date", "expiry_date", "file_url"]


def _absolute_photo_url(obj_photo, request):
    """Rend l'URL absolue d'un ImageField, ou None si vide."""
    if not obj_photo:
        return None
    try:
        url = obj_photo.url
    except (ValueError, AttributeError):
        return None
    if request is None:
        return url
    return request.build_absolute_uri(url)


_VEHICLE_STATUS_LABEL = {
    Vehicle.Status.AVAILABLE: "active",
    Vehicle.Status.IN_USE: "active",
    Vehicle.Status.MAINTENANCE: "maintenance",
    Vehicle.Status.DECOMMISSIONED: "decommissioned",
}


class DriverMiniSerializer(serializers.ModelSerializer):
    """Mini-sérialiseur pour exposer un chauffeur en lecture seule depuis
    une autre ressource (ex. ``Vehicle.assigned_driver``)."""

    full_name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = ["id", "matricule", "full_name", "photo_url"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_full_name(self, obj) -> str:
        user = getattr(obj, "user", None)
        return getattr(user, "full_name", "") if user else ""

    @extend_schema_field(OpenApiTypes.URI)
    def get_photo_url(self, obj):
        request = self.context.get("request")
        return _absolute_photo_url(obj.photo, request)


class VehicleMaintenanceSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VehicleMaintenance
        fields = [
            "id", "vehicle", "at", "type", "odometer_km", "shop", "cost_xof",
            "notes", "created_by", "created_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_created_by_name(self, obj) -> str:
        user = obj.created_by
        if not user:
            return ""
        full = getattr(user, "get_full_name", lambda: "")() or ""
        if full:
            return full
        return getattr(user, "email", "") or ""


class VehicleMaintenanceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleMaintenance
        fields = ["id", "at", "type", "odometer_km", "shop"]


class VehicleListSerializer(serializers.ModelSerializer):
    vehicle_type = VehicleTypeMiniSerializer(read_only=True)
    location = PointFieldSerializer(read_only=True)
    photo = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            "id", "plate_number", "code", "make", "model_name", "year", "capacity",
            "status", "status_label", "vehicle_type", "location",
            "fuel_type", "transmission",
            "odometer_km", "last_service_km", "service_interval_km",
            "next_maintenance_date", "photo",
            # Ajouté le 7 oct 2026 pour le pré-remplissage du plan de sièges
            # lors de la création d'un voyage depuis le backoffice web.
            "default_seat_map",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_status_label(self, obj) -> str:
        return _VEHICLE_STATUS_LABEL.get(obj.status, obj.status)

    @extend_schema_field(OpenApiTypes.URI)
    def get_photo(self, obj):
        request = self.context.get("request")
        return _absolute_photo_url(obj.photo, request)


class VehicleDetailSerializer(VehicleListSerializer):
    documents = VehicleDocumentSerializer(many=True, read_only=True)
    assigned_driver = DriverMiniSerializer(read_only=True)
    assigned_driver_id = serializers.PrimaryKeyRelatedField(
        source="assigned_driver",
        queryset=Driver.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    recent_maintenances = serializers.SerializerMethodField()

    class Meta(VehicleListSerializer.Meta):
        fields = [
            *VehicleListSerializer.Meta.fields,
            "vin", "engine_no", "traccar_device_id", "metadata",
            "created_at", "updated_at", "documents",
            "assigned_driver", "assigned_driver_id",
            "recent_maintenances",
        ]

    @extend_schema_field(
        {"type": "array", "items": {"type": "object"}},
    )
    def get_recent_maintenances(self, obj):
        qs = obj.maintenances.all()[:5]
        return VehicleMaintenanceMiniSerializer(qs, many=True).data


class VehicleCreateSerializer(serializers.ModelSerializer):
    assigned_driver_id = serializers.PrimaryKeyRelatedField(
        source="assigned_driver",
        queryset=Driver.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Vehicle
        fields = [
            "vehicle_type", "plate_number", "code", "make", "model_name", "year",
            "capacity", "vin", "engine_no", "fuel_type", "transmission",
            "odometer_km", "last_service_km", "service_interval_km",
            "next_maintenance_date", "photo",
            "traccar_device_id", "metadata",
            "default_seat_map", "assigned_driver_id",
        ]


class DriverUserMiniSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "phone"]


_DRIVER_STATUS_LABEL = {
    Driver.Status.AVAILABLE: "active",
    Driver.Status.ON_TRIP: "active",
    Driver.Status.OFF_DUTY: "leave",
}


class VehicleMiniSerializer(serializers.ModelSerializer):
    """Mini-sérialiseur pour l'exposition inverse de ``Driver.assigned_vehicles``."""

    class Meta:
        model = Vehicle
        fields = ["id", "plate_number", "make", "model_name"]


class DriverHRNoteSerializer(serializers.ModelSerializer):
    by_name = serializers.SerializerMethodField()

    class Meta:
        model = DriverHRNote
        fields = [
            "id", "driver", "by", "by_name", "text", "kind",
            "created_at", "updated_at",
        ]
        read_only_fields = ["by", "created_at", "updated_at"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_by_name(self, obj) -> str:
        user = obj.by
        if not user:
            return ""
        full = getattr(user, "get_full_name", lambda: "")() or ""
        if full:
            return full
        return getattr(user, "email", "") or ""


class DriverHRNoteMiniSerializer(serializers.ModelSerializer):
    by_name = serializers.SerializerMethodField()

    class Meta:
        model = DriverHRNote
        fields = ["id", "created_at", "kind", "text", "by_name"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_by_name(self, obj) -> str:
        user = obj.by
        if not user:
            return ""
        full = getattr(user, "get_full_name", lambda: "")() or ""
        if full:
            return full
        return getattr(user, "email", "") or ""


class DriverDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = DriverDocument
        fields = [
            "id", "driver", "type", "number", "issue_date", "expiry_date",
            "file", "file_url", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    @extend_schema_field(OpenApiTypes.URI)
    def get_file_url(self, obj):
        if not obj.file:
            return None
        try:
            url = obj.file.url
        except (ValueError, AttributeError):
            return None
        request = self.context.get("request")
        if request is None:
            return url
        return request.build_absolute_uri(url)


class DriverListSerializer(serializers.ModelSerializer):
    user = DriverUserMiniSerializer(read_only=True)
    # Alias plats ajoutés le 7 oct 2026 pour simplifier l'accès côté
    # backoffice web (driver.full_name au lieu de driver.user.full_name).
    # Le nesté `user` est préservé pour les apps mobiles RN existantes.
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_phone = serializers.CharField(
        source="user.phone", read_only=True, allow_null=True,
    )
    user_email = serializers.CharField(
        source="user.email", read_only=True, allow_null=True,
    )
    photo = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    is_on_trip = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            "id", "user", "full_name", "user_phone", "user_email",
            "matricule",
            "license_number", "license_class", "license_classes",
            "license_issued", "license_expiry", "medical_check_expiry",
            "hire_date",
            "status", "status_label", "is_on_trip", "score",
            "photo",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_status_label(self, obj) -> str:
        return _DRIVER_STATUS_LABEL.get(obj.status, obj.status)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_on_trip(self, obj) -> bool:
        return obj.is_on_trip

    @extend_schema_field(OpenApiTypes.URI)
    def get_photo(self, obj):
        request = self.context.get("request")
        return _absolute_photo_url(obj.photo, request)


class DriverDetailSerializer(DriverListSerializer):
    last_known_location = PointFieldSerializer(read_only=True)
    recent_hr_notes = serializers.SerializerMethodField()
    documents_count = serializers.IntegerField(read_only=True, default=0)
    assigned_vehicles = serializers.SerializerMethodField()

    class Meta(DriverListSerializer.Meta):
        fields = [
            *DriverListSerializer.Meta.fields,
            "birth_date", "birth_place", "address",
            "emergency_contact_name", "emergency_contact_phone",
            "last_known_location", "created_at", "updated_at", "tenant",
            "recent_hr_notes", "documents_count", "assigned_vehicles",
        ]

    @extend_schema_field({"type": "array", "items": {"type": "object"}})
    def get_recent_hr_notes(self, obj):
        qs = obj.hr_notes.all()[:5]
        return DriverHRNoteMiniSerializer(qs, many=True).data

    @extend_schema_field({"type": "array", "items": {"type": "object"}})
    def get_assigned_vehicles(self, obj):
        return VehicleMiniSerializer(obj.assigned_vehicles.all(), many=True).data


class DriverCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "user", "matricule",
            "license_number", "license_class", "license_classes",
            "license_issued", "license_expiry", "medical_check_expiry",
            "hire_date", "birth_date", "birth_place", "address",
            "emergency_contact_name", "emergency_contact_phone",
            "photo",
        ]

    def validate_user(self, user):
        request = self.context["request"]
        if user.tenant_id != request.tenant_id:
            raise serializers.ValidationError("L'utilisateur n'appartient pas à ce tenant.")
        if user.role != User.Role.DRIVER:
            raise serializers.ValidationError("L'utilisateur doit avoir le rôle 'driver'.")
        return user


class FleetManagerMiniSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name"]


class FleetSerializer(serializers.ModelSerializer):
    manager = FleetManagerMiniSerializer(read_only=True)
    vehicle_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Fleet
        fields = ["id", "name", "zone", "manager", "vehicle_count"]


class FleetCreateSerializer(serializers.ModelSerializer):
    vehicle_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True, default=list,
    )

    class Meta:
        model = Fleet
        fields = ["name", "zone", "manager", "vehicle_ids"]
        extra_kwargs = {"manager": {"required": False, "allow_null": True}}

    def create(self, validated_data):
        vehicle_ids = validated_data.pop("vehicle_ids", [])
        fleet = Fleet.objects.create(**validated_data)
        for vehicle_id in vehicle_ids:
            FleetVehicle.objects.create(fleet=fleet, vehicle_id=vehicle_id)
        return fleet
