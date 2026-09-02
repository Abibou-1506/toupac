"""TOUPAC Voyage — Serializers DRF."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from colis.serializers import TripOrderSerializer

from .models import (
    Controller,
    ControlSession,
    LuggagePolicy,
    Passenger,
    Reservation,
    Route,
    RouteStop,
    Schedule,
    SeatMap,
    Trip,
    TripStop,
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

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_vehicle(self, obj):
        return obj.vehicle.plate_number if obj.vehicle else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_driver(self, obj):
        return obj.driver.user.full_name if obj.driver else None


class TripDetailSerializer(TripListSerializer):
    stops = TripStopSerializer(many=True, read_only=True)

    class Meta(TripListSerializer.Meta):
        fields = [
            *TripListSerializer.Meta.fields,
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


class ManifestTripSerializer(TripDetailSerializer):
    """Voyage tel qu'exposé dans le manifest — seat_map nichée en entier.

    L'app offline a besoin du layout complet pour dessiner le plan de sièges
    sans requête supplémentaire : un simple UUID ne lui sert à rien.
    """
    seat_map = SeatMapSerializer(read_only=True)


class SeatOccupationSerializer(serializers.Serializer):
    """État d'un siège. `passenger_name`/`reservation_id` absents si libre."""
    status = serializers.CharField(help_text="free, booked, checked_in, boarded, no_show")
    passenger_name = serializers.CharField(required=False)
    reservation_id = serializers.UUIDField(required=False)


class ManifestPricingSerializer(serializers.Serializer):
    default_price_xof = serializers.IntegerField()
    currency = serializers.CharField()
    luggage_policy = LuggagePolicySerializer(allow_null=True)


class ManifestSessionSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    controller_name = serializers.CharField()
    device_id = serializers.CharField(allow_blank=True)


class ManifestStatsSerializer(serializers.Serializer):
    total_seats = serializers.IntegerField()
    booked = serializers.IntegerField()
    boarded = serializers.IntegerField()
    no_show = serializers.IntegerField()
    refused = serializers.IntegerField()
    revenue_xof = serializers.IntegerField()
    cash_xof = serializers.IntegerField()
    parcels_count = serializers.IntegerField()


class ManifestSerializer(serializers.Serializer):
    """Serializer custom — données complètes d'un voyage pour l'app offline.

    Tout ce dont le contrôleur a besoin pour travailler sans réseau doit tenir
    dans cette réponse : c'est le seul appel qu'il fera avant de perdre la
    connexion.
    """
    trip = ManifestTripSerializer()
    reservations = ReservationSerializer(many=True)
    passengers = PassengerSerializer(many=True)
    seat_occupation = serializers.DictField(child=SeatOccupationSerializer())
    parcels = TripOrderSerializer(many=True)
    pricing = ManifestPricingSerializer()
    active_session = ManifestSessionSerializer(allow_null=True)
    stats = ManifestStatsSerializer()
    qr_public_key = serializers.CharField(
        allow_null=True,
        help_text="Clé publique PEM pour vérifier les QR hors ligne (RS256). "
                  "null tant que la signature est en HS256.",
    )


class ControlSessionConflictSerializer(serializers.Serializer):
    """Réponse 409 de control/open — une session est déjà ouverte sur ce voyage."""
    detail = serializers.CharField()
    existing_session = serializers.DictField()


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


# ─── Batch offline ───
# Ces serializers documentent le contrat de /control-events/batch/ pour Swagger.
# La validation réelle reste dans BatchEventProcessor : elle est par event (un
# event invalide reçoit son propre verdict) et non par requête, ce qu'un
# serializer DRF ne sait pas exprimer.

class EventInputSerializer(serializers.Serializer):
    """Format d'un event dans le batch."""
    client_uuid = serializers.UUIDField(help_text="UUID généré côté mobile, clé d'idempotence")
    event_type = serializers.ChoiceField(
        choices=[
            "reservation_board", "reservation_refuse", "reservation_special_case",
            "onboard_sale", "anomaly_create", "anomaly_resolve",
            "incident_create", "activity_transition", "parcel_verify", "parcel_refuse",
        ],
        help_text="Type d'événement",
    )
    target_type = serializers.CharField(required=False, allow_blank=True)
    target_id = serializers.UUIDField(required=False, allow_null=True)
    payload = serializers.JSONField(help_text="Données spécifiques au type d'event")
    created_at_local = serializers.DateTimeField(
        help_text="Horodatage côté device — détermine l'ordre de traitement du batch",
    )
    gps_location = serializers.JSONField(required=False, help_text='{"lat": 14.69, "lng": -17.44}')
    gps_accuracy_m = serializers.IntegerField(required=False)


class BatchRequestSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(
        required=False,
        help_text=(
            "UUID de la ControlSession à laquelle rattacher le batch. "
            "Optionnel : si absent, le backend prend la session ouverte la "
            "plus récente du contrôleur. Utile pour resynchroniser des "
            "events accumulés dans une session déjà fermée."
        ),
    )
    events = EventInputSerializer(many=True)


class EventResultSerializer(serializers.Serializer):
    client_uuid = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["accepted", "rejected", "duplicate"])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)
    anomaly = serializers.JSONField(required=False, allow_null=True)


class BatchResponseSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    processed = serializers.IntegerField()
    results = EventResultSerializer(many=True)


class QrPublicKeySerializer(serializers.Serializer):
    public_key_pem = serializers.CharField(help_text="Clé publique RS256 au format PEM.")


class QrPublicKeyUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField()
