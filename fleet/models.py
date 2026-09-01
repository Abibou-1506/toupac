"""TOUPAC Fleet — Véhicules, chauffeurs, types, documents, flottes."""
from django.contrib.gis.db import models

from core.models import SoftDeleteMixin, TenantManager, TenantModel, UUIDv7Field


class VehicleType(TenantModel):
    name = models.CharField("Nom", max_length=100)
    default_capacity = models.PositiveIntegerField("Capacité par défaut")
    fuel_type = models.CharField("Carburant", max_length=20, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "fleet_vehicle_types"
        verbose_name = "Type de véhicule"
        verbose_name_plural = "Types de véhicules"
        unique_together = [("tenant", "name")]

    def __str__(self):
        return f"{self.name} ({self.default_capacity} places)"


class Vehicle(TenantModel, SoftDeleteMixin):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        IN_USE = "in_use", "En service"
        MAINTENANCE = "maintenance", "Maintenance"
        DECOMMISSIONED = "decommissioned", "Déclassé"

    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.SET_NULL, null=True, related_name="vehicles")
    plate_number = models.CharField("Immatriculation", max_length=20)
    make = models.CharField("Marque", max_length=50, blank=True)
    model_name = models.CharField("Modèle", max_length=50, blank=True)
    year = models.PositiveSmallIntegerField("Année", null=True, blank=True)
    capacity = models.PositiveIntegerField("Capacité")
    vin = models.CharField("N° châssis", max_length=17, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    location = models.PointField("Position", geography=True, null=True, blank=True, srid=4326)
    traccar_device_id = models.CharField("ID Traccar", max_length=50, blank=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "fleet_vehicles"
        verbose_name = "Véhicule"
        verbose_name_plural = "Véhicules"
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"{self.plate_number} ({self.make} {self.model_name})"


class Driver(TenantModel, SoftDeleteMixin):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        ON_TRIP = "on_trip", "En voyage"
        OFF_DUTY = "off_duty", "Hors service"

    user = models.OneToOneField("iam.User", on_delete=models.CASCADE, related_name="driver_profile")
    license_number = models.CharField("N° permis", max_length=50, blank=True)
    license_class = models.CharField("Catégorie permis", max_length=10, blank=True)
    license_expiry = models.DateField("Expiration permis", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    score = models.DecimalField("Score", max_digits=5, decimal_places=2, default=100.00)
    last_known_location = models.PointField("Dernière position", geography=True, null=True, blank=True, srid=4326)

    objects = TenantManager()

    class Meta:
        db_table = "fleet_drivers"
        verbose_name = "Chauffeur"
        verbose_name_plural = "Chauffeurs"

    def __str__(self):
        return f"{self.user.full_name} ({self.license_number})"


class VehicleDocument(TenantModel):
    class DocType(models.TextChoices):
        INSURANCE = "insurance", "Assurance"
        REGISTRATION = "registration", "Carte grise"
        INSPECTION = "inspection", "Visite technique"
        TRANSPORT_PERMIT = "transport_permit", "Autorisation de transport"

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    type = models.CharField("Type", max_length=30, choices=DocType.choices)
    document_number = models.CharField("N° document", max_length=100, blank=True)
    issue_date = models.DateField("Date émission", null=True, blank=True)
    expiry_date = models.DateField("Date expiration", null=True, blank=True)
    file_url = models.URLField("Fichier", max_length=500, blank=True)
    status = models.CharField("Statut", max_length=20, default="valid")

    objects = TenantManager()

    class Meta:
        db_table = "fleet_vehicle_documents"
        verbose_name = "Document véhicule"
        verbose_name_plural = "Documents véhicules"

    def __str__(self):
        return f"{self.get_type_display()} — {self.vehicle.plate_number}"


class Fleet(TenantModel):
    name = models.CharField("Nom", max_length=100)
    zone = models.CharField("Zone", max_length=100, blank=True)
    manager = models.ForeignKey("iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="managed_fleets")
    vehicles = models.ManyToManyField(Vehicle, through="FleetVehicle", related_name="fleets")

    objects = TenantManager()

    class Meta:
        db_table = "fleet_fleets"
        verbose_name = "Flotte"
        verbose_name_plural = "Flottes"

    def __str__(self):
        return self.name


class FleetVehicle(models.Model):
    id = UUIDv7Field()
    fleet = models.ForeignKey(Fleet, on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_fleet_vehicles"
        unique_together = [("fleet", "vehicle")]
