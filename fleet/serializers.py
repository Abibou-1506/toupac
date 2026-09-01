"""TOUPAC Fleet — Serializers DRF."""
from django.contrib.gis.geos import Point
from rest_framework import serializers

from iam.models import User

from .models import Driver, Fleet, FleetVehicle, Vehicle, VehicleDocument, VehicleType


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


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = "__all__"


class VehicleTypeMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ["id", "name"]


class VehicleDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleDocument
        fields = "__all__"


class VehicleDocumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleDocument
        fields = ["type", "document_number", "issue_date", "expiry_date", "file_url"]


class VehicleListSerializer(serializers.ModelSerializer):
    vehicle_type = VehicleTypeMiniSerializer(read_only=True)
    location = PointFieldSerializer(read_only=True)

    class Meta:
        model = Vehicle
        fields = ["id", "plate_number", "make", "model_name", "year", "capacity", "status", "vehicle_type", "location"]


class VehicleDetailSerializer(VehicleListSerializer):
    documents = VehicleDocumentSerializer(many=True, read_only=True)

    class Meta(VehicleListSerializer.Meta):
        fields = [
            *VehicleListSerializer.Meta.fields,
            "vin", "traccar_device_id", "metadata", "created_at", "updated_at", "documents",
        ]


class VehicleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ["vehicle_type", "plate_number", "make", "model_name", "year", "capacity", "vin", "traccar_device_id", "metadata"]


class DriverUserMiniSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "phone"]


class DriverListSerializer(serializers.ModelSerializer):
    user = DriverUserMiniSerializer(read_only=True)

    class Meta:
        model = Driver
        fields = ["id", "user", "license_number", "license_class", "license_expiry", "status", "score"]


class DriverDetailSerializer(DriverListSerializer):
    last_known_location = PointFieldSerializer(read_only=True)

    class Meta(DriverListSerializer.Meta):
        fields = [*DriverListSerializer.Meta.fields, "last_known_location", "created_at", "updated_at", "tenant"]


class DriverCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = ["user", "license_number", "license_class", "license_expiry"]

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
