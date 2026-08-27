"""
TOUPAC Voyage — Transport de passagers : lignes, horaires, voyages,
réservations et contrôle à bord (port direct Sprint 2 + enrichissements).
"""
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from core.models import TenantModel, TenantManager, SoftDeleteMixin, UUIDv7Field


class LuggagePolicy(TenantModel):
    """Politique bagages applicable à une ou plusieurs routes."""
    name = models.CharField("Nom", max_length=100)
    included_kg = models.PositiveIntegerField("Kg inclus", default=0)
    max_kg = models.PositiveIntegerField("Kg maximum")
    excess_price_per_kg_xof = models.IntegerField("Prix excédent / kg (XOF)", default=0)
    max_pieces = models.PositiveSmallIntegerField("Nombre de pièces max", default=1)
    restricted_items = models.JSONField("Objets interdits", default=list, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_luggage_policies"
        verbose_name = "Politique bagages"
        verbose_name_plural = "Politiques bagages"

    def __str__(self):
        return self.name


class Route(TenantModel):
    """Ligne de transport régulière (ex : Dakar → Bamako)."""
    name = models.CharField("Nom", max_length=200)
    code = models.CharField("Code", max_length=20)
    origin_place = models.ForeignKey(
        "geo.Place", on_delete=models.PROTECT, related_name="routes_as_origin", verbose_name="Origine",
    )
    destination_place = models.ForeignKey(
        "geo.Place", on_delete=models.PROTECT, related_name="routes_as_destination", verbose_name="Destination",
    )
    distance_km = models.DecimalField("Distance (km)", max_digits=8, decimal_places=2, null=True, blank=True)
    duration_minutes = models.PositiveIntegerField("Durée (minutes)", null=True, blank=True)
    luggage_policy = models.ForeignKey(
        LuggagePolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name="routes",
    )
    is_active = models.BooleanField("Active", default=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_routes"
        verbose_name = "Route"
        verbose_name_plural = "Routes"
        unique_together = [("tenant", "code")]

    def __str__(self):
        return f"{self.name} ({self.code})"


class RouteStop(TenantModel):
    """Escale ordonnée sur une route."""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    place = models.ForeignKey("geo.Place", on_delete=models.PROTECT, related_name="route_stops")
    stop_order = models.SmallIntegerField("Ordre")
    offset_minutes = models.PositiveIntegerField("Décalage (minutes)", default=0)
    is_boarding = models.BooleanField("Embarquement possible", default=True)
    is_alighting = models.BooleanField("Débarquement possible", default=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_route_stops"
        verbose_name = "Escale"
        verbose_name_plural = "Escales"
        unique_together = [("route", "stop_order")]
        ordering = ["route", "stop_order"]

    def __str__(self):
        return f"{self.route.code} — étape {self.stop_order} ({self.place.name})"


class Schedule(TenantModel):
    """Horaire récurrent d'une route."""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="schedules")
    departure_time = models.TimeField("Heure de départ")
    days_of_week = ArrayField(
        models.SmallIntegerField(), verbose_name="Jours de la semaine",
        help_text="0=lundi ... 6=dimanche",
    )
    default_vehicle_type = models.ForeignKey(
        "fleet.VehicleType", on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules",
    )
    default_price_xof = models.IntegerField("Prix par défaut (XOF)", default=0)
    is_active = models.BooleanField("Actif", default=True)
    valid_from = models.DateField("Valide à partir de", null=True, blank=True)
    valid_until = models.DateField("Valide jusqu'à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_schedules"
        verbose_name = "Horaire"
        verbose_name_plural = "Horaires"

    def __str__(self):
        return f"{self.route.code} — {self.departure_time}"


class SeatMap(TenantModel):
    """Plan de sièges réutilisable pour un type de véhicule."""
    vehicle_type = models.ForeignKey(
        "fleet.VehicleType", on_delete=models.SET_NULL, null=True, blank=True, related_name="seat_maps",
    )
    name = models.CharField("Nom", max_length=100)
    total_seats = models.PositiveIntegerField("Nombre de sièges")
    layout = models.JSONField("Disposition", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_seat_maps"
        verbose_name = "Plan de sièges"
        verbose_name_plural = "Plans de sièges"

    def __str__(self):
        return self.name


class Trip(TenantModel):
    """Voyage physique — instance d'une route à une date donnée (table centrale)."""
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programmé"
        PREPARING = "preparing", "Préparation"
        BOARDING = "boarding", "Embarquement"
        IN_TRANSIT = "in_transit", "En route"
        AT_STOP = "at_stop", "À l'escale"
        ARRIVING = "arriving", "Arrivée"
        COMPLETED = "completed", "Terminé"
        CANCELLED = "cancelled", "Annulé"

    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name="trips")
    schedule = models.ForeignKey(Schedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="trips")
    vehicle = models.ForeignKey("fleet.Vehicle", on_delete=models.SET_NULL, null=True, blank=True, related_name="trips")
    driver = models.ForeignKey("fleet.Driver", on_delete=models.SET_NULL, null=True, blank=True, related_name="trips")
    seat_map = models.ForeignKey(SeatMap, on_delete=models.SET_NULL, null=True, blank=True, related_name="trips")
    internal_id = models.CharField("Identifiant interne", max_length=20)
    departure_date = models.DateField("Date de départ")
    scheduled_at = models.DateTimeField("Heure programmée")
    actual_departure_at = models.DateTimeField("Départ réel", null=True, blank=True)
    actual_arrival_at = models.DateTimeField("Arrivée réelle", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    total_seats = models.PositiveIntegerField("Sièges totaux")
    booked_seats = models.PositiveIntegerField("Sièges réservés", default=0)
    summary = models.JSONField("Résumé", null=True, blank=True)
    created_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="trips_created",
    )

    objects = TenantManager()

    class Meta:
        db_table = "voyage_trips"
        verbose_name = "Voyage"
        verbose_name_plural = "Voyages"
        unique_together = [("tenant", "internal_id")]
        indexes = [
            models.Index(fields=["tenant", "departure_date"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"{self.internal_id} — {self.route.code} ({self.departure_date})"


class TripStop(TenantModel):
    """Instance réelle d'une escale sur un voyage donné."""
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        ARRIVED = "arrived", "Arrivé"
        DEPARTED = "departed", "Parti"
        SKIPPED = "skipped", "Ignoré"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="stops")
    route_stop = models.ForeignKey(RouteStop, on_delete=models.PROTECT, related_name="trip_stops")
    place = models.ForeignKey("geo.Place", on_delete=models.PROTECT, related_name="trip_stops")
    stop_order = models.SmallIntegerField("Ordre")
    eta = models.DateTimeField("Heure d'arrivée prévue", null=True, blank=True)
    ata = models.DateTimeField("Heure d'arrivée réelle", null=True, blank=True)
    atd = models.DateTimeField("Heure de départ réelle", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.PENDING)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_trip_stops"
        verbose_name = "Escale de voyage"
        verbose_name_plural = "Escales de voyage"
        ordering = ["trip", "stop_order"]

    def __str__(self):
        return f"{self.trip.internal_id} — étape {self.stop_order}"


class Passenger(TenantModel, SoftDeleteMixin):
    """Passager — port direct Sprint 2. Soft-delete pour le droit RGPD à l'effacement."""
    first_name = models.CharField("Prénom", max_length=100)
    last_name = models.CharField("Nom", max_length=100)
    phone = models.CharField("Téléphone", max_length=20, blank=True)
    email = models.EmailField("Email", blank=True)
    id_type = models.CharField("Type de pièce", max_length=30, blank=True)
    id_number = models.CharField("N° pièce", max_length=50, blank=True)
    id_photo_url = models.URLField("Photo pièce", max_length=500, blank=True)
    nationality = models.CharField("Nationalité", max_length=2, blank=True)
    date_of_birth = models.DateField("Date de naissance", null=True, blank=True)
    emergency_contact_name = models.CharField("Contact urgence — nom", max_length=200, blank=True)
    emergency_contact_phone = models.CharField("Contact urgence — téléphone", max_length=20, blank=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_passengers"
        verbose_name = "Passager"
        verbose_name_plural = "Passagers"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Reservation(TenantModel):
    """Billet — port direct Sprint 2, enrichi."""
    class Status(models.TextChoices):
        BOOKED = "booked", "Réservé"
        CHECKED_IN = "checked_in", "Enregistré"
        BOARDED = "boarded", "Embarqué"
        NO_SHOW = "no_show", "Absent"
        REFUSED = "refused", "Refusé"
        CANCELLED = "cancelled", "Annulé"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="reservations")
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name="reservations")
    seat_label = models.CharField("Siège", max_length=10)
    origin_stop = models.ForeignKey(
        RouteStop, on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations_as_origin",
    )
    destination_stop = models.ForeignKey(
        RouteStop, on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations_as_destination",
    )
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.BOOKED)
    amount_xof = models.IntegerField("Montant (XOF)")
    payment_method = models.CharField("Moyen de paiement", max_length=30, blank=True)
    payment_ref = models.CharField("Référence paiement", max_length=100, blank=True)
    qr_code_jwt = models.TextField("QR code (JWT)", blank=True)
    boarded_by = models.ForeignKey(
        "Controller", on_delete=models.SET_NULL, null=True, blank=True, related_name="boarded_reservations",
    )
    boarded_at = models.DateTimeField("Embarqué à", null=True, blank=True)
    boarding_method = models.CharField("Méthode d'embarquement", max_length=30, blank=True)
    special_case_reason = models.CharField("Motif cas particulier", max_length=200, blank=True)
    refusal_reason = models.CharField("Motif de refus", max_length=200, blank=True)
    luggage = models.JSONField("Bagages", default=dict, blank=True)
    sales_channel = models.CharField("Canal de vente", max_length=30, default="counter")
    created_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations_created",
    )

    objects = TenantManager()

    class Meta:
        db_table = "voyage_reservations"
        verbose_name = "Réservation"
        verbose_name_plural = "Réservations"
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "seat_label"],
                condition=~models.Q(status__in=["cancelled", "refused"]),
                name="unique_active_seat_per_trip",
            ),
        ]

    def __str__(self):
        return f"{self.trip.internal_id} — {self.seat_label} ({self.passenger})"


class Controller(TenantModel):
    """Contrôleur — port direct Sprint 2."""
    class Status(models.TextChoices):
        ACTIVE = "active", "Actif"
        INACTIVE = "inactive", "Inactif"
        SUSPENDED = "suspended", "Suspendu"

    user = models.OneToOneField("iam.User", on_delete=models.CASCADE, related_name="controller_profile")
    matricule = models.CharField("Matricule", max_length=50)
    agency = models.CharField("Agence", max_length=100, blank=True)
    score_conformity = models.DecimalField("Score conformité", max_digits=5, decimal_places=2, default=100)
    total_trips = models.PositiveIntegerField("Voyages contrôlés", default=0)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.ACTIVE)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_controllers"
        verbose_name = "Contrôleur"
        verbose_name_plural = "Contrôleurs"
        unique_together = [("tenant", "matricule")]

    def __str__(self):
        return f"{self.user.full_name} ({self.matricule})"


class ControlSession(TenantModel):
    """Session de contrôle ouverte par un contrôleur sur un voyage."""
    class SyncState(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        SYNCING = "syncing", "Synchronisation"
        SYNCED = "synced", "Synchronisé"
        FAILED = "failed", "Échec"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="control_sessions")
    controller = models.ForeignKey(Controller, on_delete=models.PROTECT, related_name="control_sessions")
    device_id = models.CharField("ID appareil", max_length=100, blank=True)
    device_info = models.JSONField("Infos appareil", default=dict, blank=True)
    opened_at = models.DateTimeField("Ouverte à")
    closed_at = models.DateTimeField("Fermée à", null=True, blank=True)
    sync_state = models.CharField("État sync", max_length=20, choices=SyncState.choices, default=SyncState.DRAFT)
    last_sync_at = models.DateTimeField("Dernière sync", null=True, blank=True)
    close_summary = models.JSONField("Résumé de clôture", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_control_sessions"
        verbose_name = "Session de contrôle"
        verbose_name_plural = "Sessions de contrôle"

    def __str__(self):
        return f"{self.trip.internal_id} — {self.controller}"


class ControlEvent(TenantModel):
    """Événement offline émis par l'app contrôleur (idempotent via client_uuid)."""
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PROCESSED = "processed", "Traité"
        REJECTED = "rejected", "Rejeté"

    session = models.ForeignKey(ControlSession, on_delete=models.CASCADE, related_name="events")
    client_uuid = models.UUIDField("UUID client")
    event_type = models.CharField("Type d'événement", max_length=30)
    target_type = models.CharField("Type de cible", max_length=30, blank=True)
    target_id = models.UUIDField("ID cible", null=True, blank=True)
    payload = models.JSONField("Données", default=dict, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.CharField("Motif de rejet", max_length=200, blank=True)
    gps_location = models.PointField("Position GPS", geography=True, srid=4326, null=True, blank=True)
    gps_accuracy_m = models.FloatField("Précision GPS (m)", null=True, blank=True)
    created_at_local = models.DateTimeField("Créé à (heure locale appareil)")
    processed_at = models.DateTimeField("Traité à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_control_events"
        verbose_name = "Événement de contrôle"
        verbose_name_plural = "Événements de contrôle"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "client_uuid"], name="unique_control_event_client_uuid"),
        ]

    def __str__(self):
        return f"{self.event_type} ({self.client_uuid})"


class Anomaly(TenantModel):
    """Anomalie détectée pendant un contrôle."""
    class Type(models.TextChoices):
        DUPLICATE_SCAN = "duplicate_scan", "Scan en double"
        SEAT_CONFLICT = "seat_conflict", "Conflit de siège"
        PARCEL_NON_CONFORM = "parcel_non_conform", "Colis non conforme"
        EXPIRED_TICKET = "expired_ticket", "Billet expiré"
        WRONG_TRIP = "wrong_trip", "Mauvais voyage"
        OTHER = "other", "Autre"

    class Severity(models.TextChoices):
        LOW = "low", "Faible"
        MODERATE = "moderate", "Modérée"
        CRITICAL = "critical", "Critique"

    class Status(models.TextChoices):
        TO_TREAT = "to_treat", "À traiter"
        IN_PROGRESS = "in_progress", "En cours"
        RESOLVED = "resolved", "Résolue"
        IGNORED = "ignored", "Ignorée"

    session = models.ForeignKey(ControlSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="anomalies")
    event = models.ForeignKey(ControlEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="anomalies")
    type = models.CharField("Type", max_length=30, choices=Type.choices)
    severity = models.CharField("Sévérité", max_length=20, choices=Severity.choices, default=Severity.LOW)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.TO_TREAT)
    title = models.CharField("Titre", max_length=200)
    description = models.TextField("Description", blank=True)
    target_type = models.CharField("Type de cible", max_length=30, blank=True)
    target_id = models.UUIDField("ID cible", null=True, blank=True)
    evidence_urls = models.JSONField("Preuves", default=list, blank=True)
    resolved_at = models.DateTimeField("Résolue à", null=True, blank=True)
    resolution_notes = models.TextField("Notes de résolution", blank=True)
    resolved_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="anomalies_resolved",
    )

    objects = TenantManager()

    class Meta:
        db_table = "voyage_anomalies"
        verbose_name = "Anomalie"
        verbose_name_plural = "Anomalies"

    def __str__(self):
        return f"{self.get_type_display()} — {self.title}"


class Incident(TenantModel):
    """Incident signalé pendant un voyage (bagage, comportement, sécurité, panne...)."""
    class Type(models.TextChoices):
        LUGGAGE = "luggage", "Bagage"
        BEHAVIOR = "behavior", "Comportement"
        SAFETY = "safety", "Sécurité"
        BREAKDOWN = "breakdown", "Panne"
        OTHER = "other", "Autre"

    class Severity(models.TextChoices):
        LOW = "low", "Faible"
        MODERATE = "moderate", "Modérée"
        CRITICAL = "critical", "Critique"

    class Status(models.TextChoices):
        REPORTED = "reported", "Signalé"
        NOTIFIED = "notified", "Notifié"
        IN_PROGRESS = "in_progress", "En cours"
        RESOLVED = "resolved", "Résolu"

    session = models.ForeignKey(ControlSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="incidents")
    reporter = models.ForeignKey("iam.User", on_delete=models.PROTECT, related_name="incidents_reported")
    type = models.CharField("Type", max_length=30, choices=Type.choices)
    severity = models.CharField("Sévérité", max_length=20, choices=Severity.choices, default=Severity.LOW)
    title = models.CharField("Titre", max_length=200)
    description = models.TextField("Description", blank=True)
    photos_urls = models.JSONField("Photos", default=list, blank=True)
    gps_location = models.PointField("Position GPS", geography=True, srid=4326, null=True, blank=True)
    gps_address = models.CharField("Adresse GPS", max_length=500, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.REPORTED)
    dispatcher_notified = models.BooleanField("Dispatcher notifié", default=False)
    dispatcher_notified_at = models.DateTimeField("Notifié à", null=True, blank=True)
    resolved_at = models.DateTimeField("Résolu à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "voyage_incidents"
        verbose_name = "Incident"
        verbose_name_plural = "Incidents"

    def __str__(self):
        return f"{self.get_type_display()} — {self.trip.internal_id}"


class CashEntry(TenantModel):
    """Encaissement effectué à bord par un contrôleur."""
    class Reason(models.TextChoices):
        ONBOARD_SALE = "onboard_sale", "Vente à bord"
        LUGGAGE_EXCESS = "luggage_excess", "Excédent bagages"
        PENALTY = "penalty", "Pénalité"
        OTHER = "other", "Autre"

    session = models.ForeignKey(ControlSession, on_delete=models.CASCADE, related_name="cash_entries")
    reservation = models.ForeignKey(
        Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="cash_entries",
    )
    amount_xof = models.IntegerField("Montant (XOF)")
    reason = models.CharField("Motif", max_length=30, choices=Reason.choices)
    collected_by = models.ForeignKey(Controller, on_delete=models.PROTECT, related_name="cash_entries_collected")

    objects = TenantManager()

    class Meta:
        db_table = "voyage_cash_entries"
        verbose_name = "Encaissement"
        verbose_name_plural = "Encaissements"

    def __str__(self):
        return f"{self.get_reason_display()} — {self.amount_xof} XOF"


class PassengerAccessLog(models.Model):
    """Audit RGPD des accès aux données passager. Modèle simple (pas d'updated_at)."""
    class Context(models.TextChoices):
        BOARDING_CHECK = "boarding_check", "Contrôle embarquement"
        ADMIN_VIEW = "admin_view", "Consultation admin"
        EXPORT = "export", "Export"

    id = UUIDv7Field()
    tenant = models.ForeignKey("iam.Tenant", on_delete=models.CASCADE, related_name="passenger_access_logs")
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name="access_logs")
    user = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="passenger_access_logs",
    )
    context = models.CharField("Contexte", max_length=30, choices=Context.choices)
    ip_address = models.GenericIPAddressField("Adresse IP", null=True, blank=True)
    created_at = models.DateTimeField("Créé à", auto_now_add=True)

    class Meta:
        db_table = "voyage_passenger_access_logs"
        verbose_name = "Log d'accès passager"
        verbose_name_plural = "Logs d'accès passager"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_context_display()} — {self.passenger} ({self.created_at})"
