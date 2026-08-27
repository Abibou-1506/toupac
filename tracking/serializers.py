"""TOUPAC Tracking — Serializers DRF."""
import json
from datetime import timedelta

from django.contrib.gis.geos import GEOSGeometry, Point
from django.utils import timezone
from fleet.models import Vehicle
from rest_framework import serializers
from .models import Geofence, GeofenceEvent, Position, TrackingLink


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


class GeoJSONField(serializers.Field):
    """Sérialise/désérialise un champ géométrique GIS (Polygon...) en GeoJSON."""

    def to_representation(self, value):
        if value is None:
            return None
        return json.loads(value.geojson)

    def to_internal_value(self, data):
        return GEOSGeometry(json.dumps(data))


class PositionSerializer(serializers.ModelSerializer):
    location = PointFieldSerializer()

    class Meta:
        model = Position
        fields = [
            "id", "vehicle", "driver", "location", "speed_kmh", "heading",
            "accuracy_m", "altitude_m", "source", "recorded_at",
        ]


class PositionCreateSerializer(serializers.Serializer):
    vehicle_id = serializers.UUIDField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    speed_kmh = serializers.DecimalField(max_digits=6, decimal_places=1, required=False, allow_null=True)
    heading = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    accuracy_m = serializers.IntegerField(required=False, allow_null=True)
    altitude_m = serializers.IntegerField(required=False, allow_null=True)
    source = serializers.ChoiceField(choices=Position.Source.choices, required=False, default=Position.Source.DRIVER_APP)
    recorded_at = serializers.DateTimeField()

    def create(self, validated_data):
        request = self.context["request"]
        vehicle = Vehicle.objects.get(id=validated_data["vehicle_id"], tenant=request.tenant)
        return Position.objects.create(
            tenant=request.tenant,
            vehicle=vehicle,
            driver=getattr(request.user, "driver_profile", None),
            location=Point(validated_data["lng"], validated_data["lat"], srid=4326),
            speed_kmh=validated_data.get("speed_kmh"),
            heading=validated_data.get("heading"),
            accuracy_m=validated_data.get("accuracy_m"),
            altitude_m=validated_data.get("altitude_m"),
            source=validated_data.get("source", Position.Source.DRIVER_APP),
            recorded_at=validated_data["recorded_at"],
        )


class PositionBatchSerializer(serializers.Serializer):
    positions = PositionCreateSerializer(many=True)


class GeofenceSerializer(serializers.ModelSerializer):
    boundary = GeoJSONField()

    class Meta:
        model = Geofence
        fields = "__all__"


class GeofenceEventSerializer(serializers.ModelSerializer):
    geofence_name = serializers.CharField(source="geofence.name", read_only=True)
    vehicle_plate = serializers.CharField(source="vehicle.plate_number", read_only=True)

    class Meta:
        model = GeofenceEvent
        fields = "__all__"


class TrackingLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackingLink
        fields = "__all__"


class TrackingLinkCreateSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=TrackingLink.ResourceType.choices)
    resource_id = serializers.UUIDField()
    expires_in_hours = serializers.IntegerField(default=72, min_value=1)

    def create(self, validated_data):
        request = self.context["request"]
        expires_at = timezone.now() + timedelta(hours=validated_data["expires_in_hours"])
        return TrackingLink.objects.create(
            tenant=request.tenant,
            token=TrackingLink.generate_token(),
            resource_type=validated_data["resource_type"],
            resource_id=validated_data["resource_id"],
            expires_at=expires_at,
        )


class PublicTrackingSerializer(serializers.Serializer):
    """Serializer custom (pas de ModelSerializer) — vue publique de suivi."""
    resource_type = serializers.CharField()
    resource_id = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    last_position = serializers.DictField(allow_null=True)
    route_name = serializers.CharField(allow_blank=True)
    tracking_number = serializers.CharField(allow_blank=True)
