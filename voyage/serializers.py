"""TOUPAC Voyage — Serializers DRF."""
import re
from datetime import date

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from colis.serializers import GeoJSONField, TripOrderSerializer

from .models import (
    Controller,
    ControlSession,
    Incident,
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
from .services.exceptions import RejectionCode


class LuggagePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = LuggagePolicy
        fields = "__all__"


class RouteStopSerializer(serializers.ModelSerializer):
    place_name = serializers.CharField(source="place.name", read_only=True)
    # Ajouté le 7 oct 2026 pour la page création voyage du backoffice web :
    # animation polyline Leaflet des escales. GeoJSONField ré-utilisé depuis
    # colis.serializers (déjà importé). Non-breaking pour RN mobile apps.
    place_location = GeoJSONField(source="place.location", read_only=True, allow_null=True)

    class Meta:
        model = RouteStop
        fields = [
            "id", "route", "place", "place_name", "place_location",
            "stop_order",
            # V1.1 : scission arrival/departure pour modéliser les pauses
            # longues (Tambacounda 30 min, déjeuner Kayes). `offset_minutes`
            # reste exposé en read-only pour compat RN mobile (ManifestSerializer).
            "arrival_offset_minutes", "departure_offset_minutes",
            "offset_minutes",
            "is_boarding", "is_alighting",
            "created_at", "updated_at",
        ]
        read_only_fields = ["offset_minutes"]


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
    """Serializer SeatMap avec validation du layout + usage_count annoté.

    `layout` est une grille 2D (liste de rangées) où chaque cellule est :
    - un objet `{"label": "A1"}` pour un siège passager
    - un objet `{"label": "DRV", "type": "driver"}` pour une cellule
      spéciale (hors comptage des sièges)
    - `null` pour une allée ou un espace vide

    Contraintes validées à la création/modification depuis V1.1 :
    - Grille rectangulaire (toutes les rangées ont la même largeur)
    - Labels de sièges uniques (hors cellules spéciales)
    - `total_seats` cohérent avec le nombre de cellules de type seat
    """

    # Compté par le ViewSet via Count('trips') annoté (pas de N+1 en liste).
    # Pour les contextes où l'instance n'est pas annotée (ex. SeatMap niché
    # dans ManifestTripSerializer), on tombe sur un count direct — rare et
    # borné par la cardinalité (1 instance), donc acceptable.
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = SeatMap
        fields = "__all__"
        # tenant est injecté par la vue (perform_create) ; is_template n'est
        # écrit que par la migration data (jamais depuis l'API).
        read_only_fields = ["tenant", "is_template", "created_at", "updated_at"]

    @extend_schema_field(serializers.IntegerField())
    def get_usage_count(self, obj):
        annotated = getattr(obj, "usage_count", None)
        if annotated is not None:
            return annotated
        return obj.trips.count()

    def validate_layout(self, value):
        if not isinstance(value, list) or len(value) == 0:
            raise serializers.ValidationError(
                "Le layout doit être un tableau de rangées non vide."
            )
        widths = {len(row) for row in value if isinstance(row, list)}
        if len(widths) != 1:
            raise serializers.ValidationError(
                "Toutes les rangées doivent avoir la même largeur."
            )
        seen_labels = set()
        for row in value:
            if not isinstance(row, list):
                raise serializers.ValidationError(
                    "Chaque rangée doit être un tableau."
                )
            for cell in row:
                if cell is None:
                    continue
                if not isinstance(cell, dict) or "label" not in cell:
                    raise serializers.ValidationError(
                        "Chaque cellule doit être null ou un objet avec un "
                        "champ 'label'."
                    )
                cell_type = cell.get("type", "seat")
                if cell_type == "seat":
                    label = cell["label"]
                    if label in seen_labels:
                        raise serializers.ValidationError(
                            f"Label de siège '{label}' dupliqué."
                        )
                    seen_labels.add(label)
        return value

    def validate(self, attrs):
        """Vérifie que `total_seats` correspond au count de sièges du layout.

        Appliqué uniquement si les deux champs sont pertinents pour la
        requête (création = les deux ; patch partiel = on utilise la
        valeur persistée pour ce qui n'est pas fourni).
        """
        layout = attrs.get(
            "layout", self.instance.layout if self.instance else None
        )
        total_seats = attrs.get(
            "total_seats", self.instance.total_seats if self.instance else None
        )
        if layout and total_seats is not None:
            seat_count = sum(
                1
                for row in layout
                for cell in row
                if cell is not None and cell.get("type", "seat") == "seat"
            )
            if seat_count != total_seats:
                raise serializers.ValidationError({
                    "total_seats": (
                        f"Le layout contient {seat_count} sièges mais "
                        f"total_seats est à {total_seats}."
                    )
                })
        return attrs


class RouteMiniSerializer(serializers.ModelSerializer):
    """Représentation compacte d'une route, nichée dans les serializers Trip.

    `distance_km` et `duration_minutes` sont inclus depuis le 5 oct 2026 pour
    permettre au backoffice web d'afficher la durée estimée et la distance
    dans le détail voyage (InfosCard + KPIs Suivi). Non-breaking pour les
    apps mobiles RN qui ignorent les champs non attendus.
    """
    class Meta:
        model = Route
        fields = ["id", "name", "code", "distance_km", "duration_minutes"]


class TripStopSerializer(serializers.ModelSerializer):
    place_name = serializers.CharField(source="place.name", read_only=True)
    # Dérivés du `RouteStop` parent — l'app offline en a besoin pour afficher
    # les options d'embarquement et de descente **à bord**, et depuis la vente
    # à bord sur trajet partiel (ticket du 1er oct), pour que le contrôleur
    # choisisse une origine/destination autorisée sans aller-retour serveur.
    #
    # Le `source="route_stop.…"` déclenche un lookup : la queryset qui alimente
    # le manifest doit `prefetch_related("stops__route_stop")`, sinon on paye un
    # N+1 silencieux. Vérifié dans `TripViewSet.get_queryset`.
    is_boarding = serializers.BooleanField(source="route_stop.is_boarding", read_only=True)
    is_alighting = serializers.BooleanField(source="route_stop.is_alighting", read_only=True)

    class Meta:
        model = TripStop
        fields = [
            "id", "trip", "route_stop", "place", "place_name", "stop_order",
            "eta", "ata", "atd", "status",
            "is_boarding", "is_alighting",
            "created_at", "updated_at",
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
    # Depuis Prompt 8 Bug C : expose le plan de sièges niché pour que le
    # backoffice web puisse afficher le Dialog visionneuse SeatMap sans
    # refetch séparé. Lecture seule — la modification du plan passe par
    # `/voyage/seat-maps/`.
    seat_map = SeatMapSerializer(read_only=True)

    class Meta(TripListSerializer.Meta):
        fields = [
            *TripListSerializer.Meta.fields,
            "actual_departure_at", "actual_arrival_at", "seat_map",
            "summary", "created_at", "stops",
        ]


_TRIP_INTERNAL_ID_PATTERN = re.compile(r"^T-([A-Z]+)-\d{8}-\d+$")


def _generate_trip_internal_id(tenant):
    """Génère un `internal_id` Trip au format `T-{PREFIX}-{YYYYMMDD}-{NN}`.

    Même logique que `_generate_order_internal_id` dans `colis.serializers` :
    prefix extrait du dernier Trip du tenant (continuité avec le seed, ex.
    'TPC' pour TOUPAC), fallback sur slug[:3].upper() pour un nouveau tenant.
    Les deux helpers ne sont pas mutualisés : les patterns divergent (`T-` vs
    `CMD-`) et peuvent évoluer indépendamment.
    """
    today = date.today()
    date_str = today.strftime("%Y%m%d")

    last_trip = (
        Trip.objects.filter(tenant=tenant).order_by("-created_at").first()
    )
    prefix = (tenant.slug[:3] or "TNT").upper()
    if last_trip:
        match = _TRIP_INTERNAL_ID_PATTERN.match(last_trip.internal_id)
        if match:
            prefix = match.group(1)

    prefix_today = f"T-{prefix}-{date_str}-"
    count = Trip.objects.filter(
        tenant=tenant,
        internal_id__startswith=prefix_today,
    ).count()
    return f"T-{prefix}-{date_str}-{count:02d}"


class TripCreateSerializer(serializers.ModelSerializer):
    """Serializer de création de voyage.

    `internal_id` est généré au format `T-{PREFIX}-{YYYYMMDD}-{NN}` si non
    fourni. Les apps mobiles RN qui fournissent explicitement un `internal_id`
    conservent leur contrat.

    `summary` reste read_only — il est calculé par `build_trip_summary()`
    à la clôture de session de contrôle, pas en création.
    """
    class Meta:
        model = Trip
        fields = [
            "id", "route", "schedule", "vehicle", "driver", "seat_map",
            "internal_id", "departure_date", "scheduled_at",
            "actual_departure_at", "actual_arrival_at", "status",
            "total_seats", "booked_seats", "summary", "created_by",
        ]
        read_only_fields = ["id", "summary", "created_by"]
        extra_kwargs = {
            "internal_id": {"required": False, "allow_blank": True},
        }

    def create(self, validated_data):
        if not validated_data.get("internal_id"):
            tenant = validated_data.get("tenant") or self.context["request"].tenant
            validated_data["internal_id"] = _generate_trip_internal_id(tenant)
        return super().create(validated_data)


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


class IncidentListSerializer(serializers.ModelSerializer):
    """Liste des incidents — colonnes clés pour l'écran /incidents du backoffice."""
    trip_internal_id = serializers.CharField(source="trip.internal_id", read_only=True)
    trip_route_name = serializers.CharField(source="trip.route.name", read_only=True)
    reporter_name = serializers.CharField(source="reporter.full_name", read_only=True)

    class Meta:
        model = Incident
        fields = [
            "id", "trip", "trip_internal_id", "trip_route_name",
            "reporter", "reporter_name",
            "type", "severity", "title", "status",
            "dispatcher_notified", "dispatcher_notified_at",
            "resolved_at", "created_at",
        ]


class IncidentDetailSerializer(serializers.ModelSerializer):
    """Détail d'un incident — tous les champs utiles pour la fiche.

    `gps_location` est sérialisé en GeoJSON Point via `GeoJSONField` (porté
    depuis colis/serializers.py), parce que le PointField PostGIS natif ne
    rend pas une représentation JSON exploitable côté backoffice web.
    """
    trip_internal_id = serializers.CharField(source="trip.internal_id", read_only=True)
    trip_route_name = serializers.CharField(source="trip.route.name", read_only=True)
    reporter_name = serializers.CharField(source="reporter.full_name", read_only=True)
    session_opened_at = serializers.DateTimeField(
        source="session.opened_at", read_only=True, allow_null=True,
    )
    gps_location = GeoJSONField(read_only=True, allow_null=True)

    class Meta:
        model = Incident
        fields = [
            "id", "trip", "trip_internal_id", "trip_route_name",
            "session", "session_opened_at",
            "reporter", "reporter_name",
            "type", "severity", "title", "description",
            "photos_urls", "gps_location", "gps_address",
            "status", "dispatcher_notified", "dispatcher_notified_at",
            "resolved_at", "created_at", "updated_at",
        ]


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
    """
    Verdict d'un event du batch.

    Les trois champs optionnels ne sont présents que quand ils ont un sens :
    les deux champs de rejet sur un rejet, `details` sur un event accepté par un
    handler qui en produit. Leur absence est donc informative — l'app n'a pas à
    distinguer « vide » de « pas concerné ».
    """

    client_uuid = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["accepted", "rejected", "duplicate"])
    rejection_code = serializers.ChoiceField(
        choices=[(code.value, code.value) for code in RejectionCode],
        required=False,
        help_text=(
            "Motif de rejet sous forme stable, en SCREAMING_SNAKE. Destiné au "
            "code de l'app : contrairement à `rejection_reason`, il ne changera "
            "pas au gré des reformulations. Absent si l'event n'est pas rejeté. "
            "La liste exhaustive est maintenue dans "
            "`voyage.services.exceptions.RejectionCode` ; chaque valeur ajoutée "
            "y entre avant d'apparaître ici."
        ),
    )
    rejection_reason = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Le même motif en français, destiné à l'affichage.",
    )
    anomaly = serializers.JSONField(required=False, allow_null=True)
    details = serializers.JSONField(
        required=False,
        help_text=(
            "Ce que le handler a produit et que l'app peut utiliser sans "
            "refetcher le manifeste : identifiants créés (`reservation_id`, "
            "`passenger_id`, `cash_entry_id`…) et statuts à jour "
            "(`reservation_status`, `trip_status`). Les clés dépendent du type "
            "d'event et sont une liste blanche côté serveur."
        ),
    )


class BatchResponseSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    processed = serializers.IntegerField()
    results = EventResultSerializer(many=True)


class QrPublicKeySerializer(serializers.Serializer):
    public_key_pem = serializers.CharField(help_text="Clé publique RS256 au format PEM.")


class QrPublicKeyUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField()
