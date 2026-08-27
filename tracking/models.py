"""TOUPAC Tracking — Positions GPS, géofences, suivi public."""
import secrets

from django.contrib.gis.db import models
from core.models import TenantModel, TenantManager


class Position(models.Model):
    """
    Position GPS d'un véhicule. Table la plus volumineuse du projet — pas de
    TenantModel (pas de updated_at, PK bigint pour la volumétrie).
    """
    class Source(models.TextChoices):
        TRACCAR = "traccar", "Traccar"
        DRIVER_APP = "driver_app", "App chauffeur"
        MANUAL = "manual", "Manuel"

    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("iam.Tenant", on_delete=models.CASCADE, related_name="positions")
    vehicle = models.ForeignKey("fleet.Vehicle", on_delete=models.CASCADE, related_name="positions")
    driver = models.ForeignKey(
        "fleet.Driver", on_delete=models.SET_NULL, null=True, blank=True, related_name="positions",
    )
    location = models.PointField("Position", geography=True, srid=4326)
    speed_kmh = models.DecimalField("Vitesse (km/h)", max_digits=6, decimal_places=1, null=True, blank=True)
    heading = models.DecimalField("Cap (azimut)", max_digits=5, decimal_places=1, null=True, blank=True)
    accuracy_m = models.PositiveSmallIntegerField("Précision (m)", null=True, blank=True)
    altitude_m = models.SmallIntegerField("Altitude (m)", null=True, blank=True)
    source = models.CharField("Source", max_length=10, choices=Source.choices, default=Source.DRIVER_APP)
    recorded_at = models.DateTimeField("Capturée à", db_index=True)
    created_at = models.DateTimeField("Créée à", auto_now_add=True)

    class Meta:
        db_table = "tracking_positions"
        verbose_name = "Position"
        verbose_name_plural = "Positions"
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["vehicle", "-recorded_at"]),
            models.Index(fields=["tenant", "-recorded_at"]),
        ]

    def __str__(self):
        return f"Position {self.vehicle} @ {self.recorded_at}"


class Geofence(TenantModel):
    """Zone géographique surveillée (dépôt, hub, site client, zone restreinte...)."""
    class FenceType(models.TextChoices):
        DEPOT = "depot", "Dépôt"
        HUB = "hub", "Hub logistique"
        CLIENT_SITE = "client_site", "Site client"
        RESTRICTED = "restricted", "Zone restreinte"
        COUNTRY_BORDER = "country_border", "Frontière"

    name = models.CharField("Nom", max_length=100)
    type = models.CharField("Type", max_length=20, choices=FenceType.choices)
    boundary = models.PolygonField("Périmètre", geography=True, srid=4326)
    is_active = models.BooleanField("Active", default=True)
    alert_rules = models.JSONField("Règles d'alerte", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "tracking_geofences"
        verbose_name = "Géofence"
        verbose_name_plural = "Géofences"

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class GeofenceEvent(TenantModel):
    """Événement d'entrée/sortie/stationnement d'un véhicule dans une géofence."""
    class EventType(models.TextChoices):
        ENTER = "enter", "Entrée"
        EXIT = "exit", "Sortie"
        DWELL = "dwell", "Stationnement"

    geofence = models.ForeignKey(Geofence, on_delete=models.CASCADE, related_name="events")
    vehicle = models.ForeignKey("fleet.Vehicle", on_delete=models.CASCADE, related_name="geofence_events")
    event_type = models.CharField("Type", max_length=10, choices=EventType.choices)
    event_at = models.DateTimeField("Survenu à")

    objects = TenantManager()

    class Meta:
        db_table = "tracking_geofence_events"
        verbose_name = "Événement géofence"
        verbose_name_plural = "Événements géofence"
        ordering = ["-event_at"]

    def __str__(self):
        return f"{self.get_event_type_display()} — {self.vehicle} @ {self.geofence.name}"


class TrackingLink(TenantModel):
    """URL publique de suivi (voyage ou colis), sans authentification."""
    class ResourceType(models.TextChoices):
        ORDER = "order", "Commande colis"
        TRIP = "trip", "Voyage"

    token = models.CharField("Token", max_length=32, unique=True)
    resource_type = models.CharField("Type de ressource", max_length=10, choices=ResourceType.choices)
    resource_id = models.UUIDField("ID ressource")
    expires_at = models.DateTimeField("Expire à")

    objects = TenantManager()

    class Meta:
        db_table = "tracking_links"
        verbose_name = "Lien de suivi"
        verbose_name_plural = "Liens de suivi"

    def __str__(self):
        return f"Link {self.token} → {self.resource_type}/{self.resource_id}"

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(24)[:32]
