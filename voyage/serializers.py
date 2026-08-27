"""TOUPAC Voyage — Serializers DRF."""
from rest_framework import serializers
from .models import (
    LuggagePolicy, Route, RouteStop, Schedule, SeatMap, Trip, TripStop,
    Passenger, Reservation, Controller, ControlSession,
)


class LuggagePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LuggagePolicy
        fields = "__all__"


class RouteStopSerializer(serializers.ModelSerializer):
    place_name = serializers.CharField(source="place.name", read_only=True)

    class Meta:
        model = RouteStop
        fields = [
            "id", "route", "place", "place_name", "stop_order",
            "offset_minutes", "is_boarding", "is_alighting",
            "created_at", "updated_at",
        ]


class RouteSerializer(serializers.ModelSerializer):
    # Pas de source="stops" : DRF interdit un source identique au nom du champ.
    stops = RouteStopSerializer(many=True, read_only=True)

    class Meta:
        model = Route
        fields = "__all__"


class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = "__all__"


class SeatMapSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeatMap
        fields = "__all__"


class RouteMiniSerializer(serializers.ModelSerializer):
    """Représentation compacte d'une route, nichée dans les serializers Trip."""
    class Meta:
        model = Route
        fields = ["id", "name", "code"]


class TripStopSerializer(serializers.ModelSerializer):
    place_name = serializers.CharField(source="place.name", read_only=True)

    class Meta:
        model = TripStop
        fields = [
            "id", "trip", "route_stop", "place", "place_name", "stop_order",
            "eta", "ata", "atd", "status", "created_at", "updated_at",
        ]


class TripListSerializer(serializers.ModelSerializer):
    route = RouteMiniSerializer(read_only=True)
    vehicle = serializers.SerializerMethodField()
    driver = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id", "internal_id", "route", "departure_date", "scheduled_at",
            "status", "total_seats", "booked_seats", "vehicle", "driver",
        ]

    def get_vehicle(self, obj):
        return obj.vehicle.plate_number if obj.vehicle else None

    def get_driver(self, obj):
        return obj.driver.user.full_name if obj.driver else None


class TripDetailSerializer(TripListSerializer):
    stops = TripStopSerializer(many=True, read_only=True)

    class Meta(TripListSerializer.Meta):
        fields = TripListSerializer.Meta.fields + [
            "actual_departure_at", "actual_arrival_at", "seat_map",
            "summary", "created_at", "stops",
        ]


class TripCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = [
            "id", "route", "schedule", "vehicle", "driver", "seat_map",
            "internal_id", "departure_date", "scheduled_at",
            "actual_departure_at", "actual_arrival_at", "status",
            "total_seats", "booked_seats", "summary", "created_by",
        ]
        read_only_fields = ["id", "created_by"]


class PassengerSerializer(serializers.ModelSerializer):
    """Exclut id_number/id_photo_url par défaut (données sensibles RGPD)."""
    ID_CARD_FIELDS = ("id_number", "id_photo_url")

    class Meta:
        model = Passenger
        fields = "__all__"

    def __init__(self, *args, include_id_card=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_id_card:
            for field_name in self.ID_CARD_FIELDS:
                self.fields.pop(field_name, None)


class ReservationSerializer(serializers.ModelSerializer):
    passenger_name = serializers.CharField(source="passenger.full_name", read_only=True)
    trip_internal_id = serializers.CharField(source="trip.internal_id", read_only=True)

    class Meta:
        model = Reservation
        fields = "__all__"


class ReservationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            "trip", "passenger", "seat_label", "origin_stop", "destination_stop",
            "amount_xof", "payment_method", "sales_channel",
        ]
        extra_kwargs = {
            "origin_stop": {"required": False, "allow_null": True},
            "destination_stop": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        trip = attrs["trip"]
        seat_label = attrs["seat_label"]
        conflict = Reservation.objects.filter(
            trip=trip, seat_label=seat_label,
        ).exclude(status__in=["cancelled", "refused"]).exists()
        if conflict:
            raise serializers.ValidationError(
                {"seat_label": "Ce siège est déjà réservé pour ce voyage."}
            )
        return attrs


class ManifestSerializer(serializers.Serializer):
    """Serializer custom — données complètes d'un voyage pour l'app offline."""
    trip = TripDetailSerializer()
    reservations = ReservationSerializer(many=True)
    passengers = PassengerSerializer(many=True)
    stats = serializers.DictField()


class BoardingActionSerializer(serializers.Serializer):
    boarding_method = serializers.CharField(required=False, default="qr_scan")
    special_case_reason = serializers.CharField(required=False, allow_blank=True, default="")
    refusal_reason = serializers.CharField(required=False, allow_blank=True, default="")


class ControllerSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Controller
        fields = "__all__"


class ControlSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlSession
        fields = "__all__"


class ControlOpenSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True)
    device_info = serializers.JSONField(required=False, default=dict)


class ControlCloseSerializer(serializers.Serializer):
    close_summary = serializers.JSONField(required=True)
