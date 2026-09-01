"""TOUPAC Geo — Serializers DRF."""
import json

from django.contrib.gis.geos import GEOSGeometry, Point
from rest_framework import serializers

from .models import Place, Zone


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


class PlaceListSerializer(serializers.ModelSerializer):
    location = PointFieldSerializer()

    class Meta:
        model = Place
        fields = ["id", "name", "address", "city", "country_code", "type", "location"]


class PlaceDetailSerializer(PlaceListSerializer):
    class Meta(PlaceListSerializer.Meta):
        fields = [*PlaceListSerializer.Meta.fields, "metadata", "tenant", "created_at"]


class PlaceCreateSerializer(serializers.ModelSerializer):
    lat = serializers.FloatField(write_only=True)
    lng = serializers.FloatField(write_only=True)

    class Meta:
        model = Place
        fields = ["name", "address", "city", "country_code", "type", "lat", "lng", "metadata"]

    def create(self, validated_data):
        lat = validated_data.pop("lat")
        lng = validated_data.pop("lng")
        validated_data["location"] = Point(lng, lat, srid=4326)
        return Place.objects.create(**validated_data)


class ZoneSerializer(serializers.ModelSerializer):
    boundary = GeoJSONField()

    class Meta:
        model = Zone
        fields = "__all__"


class ZoneCreateSerializer(serializers.ModelSerializer):
    boundary = GeoJSONField()

    class Meta:
        model = Zone
        fields = ["name", "type", "boundary", "is_active", "alert_on_exit", "metadata"]


class NearbyPlaceSerializer(PlaceListSerializer):
    distance_km = serializers.SerializerMethodField()

    class Meta(PlaceListSerializer.Meta):
        fields = [*PlaceListSerializer.Meta.fields, "distance_km"]

    def get_distance_km(self, obj):
        distance = getattr(obj, "distance", None)
        if distance is None:
            return None
        return round(distance.km, 2)
