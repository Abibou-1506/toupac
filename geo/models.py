"""TOUPAC Geo — Lieux et zones avec PostGIS."""
from django.contrib.gis.db import models

from core.models import TenantManager, TenantModel


class Place(TenantModel):
    class PlaceType(models.TextChoices):
        STATION = "station", "Gare routière"
        DEPOT = "depot", "Dépôt"
        HUB = "hub", "Hub logistique"
        CLIENT_ADDRESS = "client_address", "Adresse client"
        OTHER = "other", "Autre"

    name = models.CharField("Nom", max_length=200)
    address = models.CharField("Adresse", max_length=500, blank=True)
    city = models.CharField("Ville", max_length=100, blank=True)
    country_code = models.CharField("Pays", max_length=2, blank=True)
    location = models.PointField("Coordonnées", geography=True, srid=4326)
    type = models.CharField("Type", max_length=30, choices=PlaceType.choices, default=PlaceType.OTHER, blank=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)

    # tenant nullable pour les places partagées (gares publiques)
    tenant = models.ForeignKey(
        "iam.Tenant", on_delete=models.CASCADE, null=True, blank=True,
        related_name="places",
    )

    objects = TenantManager()

    class Meta:
        db_table = "geo_places"
        verbose_name = "Lieu"
        verbose_name_plural = "Lieux"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.city})" if self.city else self.name


class Zone(TenantModel):
    class ZoneType(models.TextChoices):
        SERVICE = "service", "Zone de service"
        GEOFENCE = "geofence", "Géofence"
        TARIFF = "tariff", "Zone tarifaire"

    name = models.CharField("Nom", max_length=100)
    type = models.CharField("Type", max_length=20, choices=ZoneType.choices)
    boundary = models.PolygonField("Périmètre", geography=True, srid=4326)
    is_active = models.BooleanField("Active", default=True)
    alert_on_exit = models.BooleanField("Alerte sortie", default=False)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "geo_zones"
        verbose_name = "Zone"
        verbose_name_plural = "Zones"

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
