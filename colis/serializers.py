"""TOUPAC Colis — Serializers DRF."""
import json

from django.contrib.gis.geos import GEOSGeometry
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import DeliveryTask, Order, Parcel, ProofOfDelivery


class GeoJSONField(serializers.Field):
    """Sérialise/désérialise un champ géométrique GIS (LineString...) en GeoJSON."""

    def to_representation(self, value):
        if value is None:
            return None
        return json.loads(value.geojson)

    def to_internal_value(self, data):
        return GEOSGeometry(json.dumps(data))


class ParcelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parcel
        fields = "__all__"


class ParcelCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parcel
        fields = [
            "order", "description", "weight_kg", "length_cm", "width_cm",
            "height_cm", "category", "declared_value_xof",
        ]
        extra_kwargs = {"order": {"required": False}}


class DeliveryTaskSerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="driver.user.full_name", read_only=True, default=None)
    order_internal_id = serializers.CharField(source="order.internal_id", read_only=True)
    place_name = serializers.CharField(source="place.name", read_only=True)
    route_geometry = GeoJSONField(required=False, allow_null=True)

    class Meta:
        model = DeliveryTask
        fields = "__all__"


class OrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    pickup_place = serializers.CharField(source="pickup_place.name", read_only=True)
    dropoff_place = serializers.CharField(source="dropoff_place.name", read_only=True)
    parcel_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Order
        fields = [
            "id", "internal_id", "customer_name", "status", "priority",
            "payment_status", "total_amount_xof", "pickup_place", "dropoff_place",
            "created_at", "parcel_count",
        ]

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_customer_name(self, obj):
        if obj.customer_id:
            return obj.customer.full_name
        return obj.customer_name


class OrderDetailSerializer(OrderListSerializer):
    parcels = ParcelSerializer(many=True, read_only=True)
    delivery_tasks = DeliveryTaskSerializer(many=True, read_only=True)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            "customer", "customer_phone", "pickup_window_start", "pickup_window_end",
            "delivery_window_start", "delivery_window_end", "instructions", "metadata",
            "created_by", "updated_at", "parcels", "delivery_tasks",
        ]


class OrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            "customer", "customer_name", "customer_phone", "pickup_place", "dropoff_place",
            "trip", "pickup_window_start", "pickup_window_end", "delivery_window_start",
            "delivery_window_end", "priority", "instructions", "metadata",
        ]
        extra_kwargs = {
            "customer": {"required": False, "allow_null": True},
            "trip": {"required": False, "allow_null": True},
        }


class TripOrderSerializer(serializers.ModelSerializer):
    """
    Commande colis telle qu'exposée dans le manifest d'un voyage.

    Le contrôleur a besoin d'identifier le colis et de joindre l'expéditeur —
    pas de la logistique de tournée (delivery_tasks, fenêtres horaires).
    """
    order_id = serializers.UUIDField(source="id", read_only=True)
    customer_name = serializers.SerializerMethodField()
    parcels = ParcelSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "order_id", "internal_id", "customer_name", "customer_phone",
            "status", "parcels",
        ]

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_customer_name(self, obj):
        if obj.customer_id:
            return obj.customer.full_name
        return obj.customer_name


class ProofOfDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProofOfDelivery
        fields = "__all__"


class ProofOfDeliveryCreateSerializer(serializers.ModelSerializer):
    gps_location = serializers.DictField(required=False, allow_null=True)

    class Meta:
        model = ProofOfDelivery
        fields = [
            "type", "signature_url", "photos_urls", "otp_code",
            "recipient_name", "recipient_phone", "notes", "gps_location",
        ]


class DispatchRequestSerializer(serializers.Serializer):
    order_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    driver_id = serializers.UUIDField()
    vehicle_id = serializers.UUIDField()

    def validate(self, attrs):
        tenant = self.context["request"].tenant
        order_ids = attrs["order_ids"]
        orders = Order.objects.filter(tenant=tenant, id__in=order_ids)
        found_ids = {str(order.id) for order in orders}
        missing = [str(oid) for oid in order_ids if str(oid) not in found_ids]
        if missing:
            raise serializers.ValidationError({"order_ids": f"Commandes introuvables : {missing}"})

        not_confirmed = [str(order.id) for order in orders if order.status != Order.Status.CONFIRMED]
        if not_confirmed:
            raise serializers.ValidationError(
                {"order_ids": f"Commandes non confirmées (status attendu 'confirmed') : {not_confirmed}"}
            )
        return attrs
