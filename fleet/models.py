"""TOUPAC Fleet — Véhicules, chauffeurs, types, documents, flottes."""
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.db.models import Q, UniqueConstraint

from core.models import SoftDeleteMixin, TenantManager, TenantModel, UUIDv7Field


class VehicleType(TenantModel):
    class Category(models.TextChoices):
        INTERURBAIN = "interurbain", "Interurbain"
        URBAIN = "urbain", "Urbain"
        UTILITAIRE = "utilitaire", "Utilitaire"

    class PermitRequired(models.TextChoices):
        B = "B", "B"
        C = "C", "C"
        D = "D", "D"
        D1 = "D1", "D1"
        BE = "BE", "BE"

    name = models.CharField("Nom", max_length=100)
    short = models.CharField("Nom court", max_length=16, blank=True)
    category = models.CharField(
        "Catégorie", max_length=20, choices=Category.choices, default=Category.INTERURBAIN,
    )
    description = models.TextField("Description", blank=True)
    default_capacity = models.PositiveIntegerField("Capacité par défaut")
    fuel_type = models.CharField("Carburant", max_length=20, blank=True)
    permit_required = models.CharField(
        "Permis requis", max_length=4, choices=PermitRequired.choices, default=PermitRequired.D,
    )
    length_m = models.DecimalField("Longueur (m)", max_digits=5, decimal_places=2, null=True, blank=True)
    width_m = models.DecimalField("Largeur (m)", max_digits=5, decimal_places=2, null=True, blank=True)
    height_m = models.DecimalField("Hauteur (m)", max_digits=5, decimal_places=2, null=True, blank=True)
    ptac_kg = models.PositiveIntegerField("PTAC (kg)", null=True, blank=True)
    hold_m3 = models.DecimalField("Soute (m³)", max_digits=5, decimal_places=2, null=True, blank=True)
    default_luggage_policy = models.ForeignKey(
        "voyage.LuggagePolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Politique bagages par défaut",
    )

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

    class FuelType(models.TextChoices):
        DIESEL = "diesel", "Diesel"
        ESSENCE = "essence", "Essence"
        GASOIL = "gasoil", "Gasoil"
        HYBRIDE = "hybride", "Hybride"

    class Transmission(models.TextChoices):
        MANUELLE = "manuelle", "Manuelle"
        AUTOMATIQUE = "automatique", "Automatique"

    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.SET_NULL, null=True, related_name="vehicles")
    plate_number = models.CharField("Immatriculation", max_length=20)
    code = models.CharField("Code interne", max_length=16, blank=True)
    make = models.CharField("Marque", max_length=50, blank=True)
    model_name = models.CharField("Modèle", max_length=50, blank=True)
    year = models.PositiveSmallIntegerField("Année", null=True, blank=True)
    capacity = models.PositiveIntegerField("Capacité")
    vin = models.CharField("N° châssis", max_length=17, blank=True)
    engine_no = models.CharField("N° moteur", max_length=50, blank=True)
    fuel_type = models.CharField(
        "Carburant", max_length=20, choices=FuelType.choices, default=FuelType.DIESEL,
    )
    transmission = models.CharField(
        "Boîte", max_length=20, choices=Transmission.choices, default=Transmission.MANUELLE,
    )
    odometer_km = models.PositiveIntegerField("Odomètre (km)", default=0)
    last_service_km = models.PositiveIntegerField("Dernière révision (km)", default=0)
    service_interval_km = models.PositiveIntegerField("Intervalle révision (km)", default=20000)
    next_maintenance_date = models.DateField("Prochaine révision", null=True, blank=True)
    photo = models.ImageField("Photo", upload_to="vehicles/photos/", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    location = models.PointField("Position", geography=True, null=True, blank=True, srid=4326)
    # FK cross-app (fleet → voyage). SET_NULL : la suppression d'un plan
    # n'invalide pas le véhicule — le trip peut toujours être créé avec un
    # autre plan au moment de la création.
    default_seat_map = models.ForeignKey(
        "voyage.SeatMap",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles_default",
        verbose_name="Plan de sièges par défaut",
        help_text=(
            "Plan utilisé par défaut lors de la création d'un voyage avec ce "
            "véhicule. Peut être overridé au moment de la création."
        ),
    )
    # Affectation RH persistante (distinct de Trip.driver runtime, qui est le
    # chauffeur du voyage courant). Permet d'exposer un lien pérenne
    # chauffeur ↔ véhicule dans la page détail backoffice. SET_NULL pour que
    # la suppression d'un chauffeur ne détruise pas le véhicule.
    assigned_driver = models.ForeignKey(
        "fleet.Driver",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_vehicles",
        verbose_name="Chauffeur affecté",
    )
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
    matricule = models.CharField("Matricule", max_length=16, blank=True)
    license_number = models.CharField("N° permis", max_length=50, blank=True)
    license_class = models.CharField("Catégorie permis", max_length=10, blank=True)
    license_classes = ArrayField(
        models.CharField(max_length=4),
        verbose_name="Catégories permis",
        default=list,
        blank=True,
    )
    license_issued = models.DateField("Date d'obtention du permis", null=True, blank=True)
    license_expiry = models.DateField("Expiration permis", null=True, blank=True)
    medical_check_expiry = models.DateField("Visite médicale (expiration)", null=True, blank=True)
    hire_date = models.DateField("Date d'embauche", null=True, blank=True)
    birth_date = models.DateField("Date de naissance", null=True, blank=True)
    birth_place = models.CharField("Lieu de naissance", max_length=100, blank=True)
    address = models.TextField("Adresse", blank=True)
    emergency_contact_name = models.CharField("Contact urgence (nom)", max_length=100, blank=True)
    emergency_contact_phone = models.CharField("Contact urgence (tél.)", max_length=20, blank=True)
    photo = models.ImageField("Photo", upload_to="drivers/photos/", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    score = models.DecimalField("Score", max_digits=5, decimal_places=2, default=100.00)
    last_known_location = models.PointField("Dernière position", geography=True, null=True, blank=True, srid=4326)

    objects = TenantManager()

    class Meta:
        db_table = "fleet_drivers"
        verbose_name = "Chauffeur"
        verbose_name_plural = "Chauffeurs"
        constraints = [
            UniqueConstraint(
                fields=["tenant", "matricule"],
                condition=~Q(matricule=""),
                name="unique_driver_matricule_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.user.full_name} ({self.license_number})"

    @property
    def is_on_trip(self) -> bool:
        """True si le chauffeur est actuellement sur un voyage actif."""
        # Import local pour éviter l'import circulaire fleet ↔ voyage.
        from voyage.models import Trip

        return Trip.objects.filter(
            driver=self,
            status__in=[
                Trip.Status.BOARDING,
                Trip.Status.IN_TRANSIT,
                Trip.Status.AT_STOP,
                Trip.Status.ARRIVING,
            ],
        ).exists()


class VehicleDocument(TenantModel):
    class DocType(models.TextChoices):
        INSURANCE = "insurance", "Assurance"
        REGISTRATION = "registration", "Carte grise"
        INSPECTION = "inspection", "Visite technique"
        TRANSPORT_PERMIT = "transport_permit", "Autorisation de transport"
        CEDEAO_GREEN_CARD = "cedeao_green_card", "Carte verte CEDEAO"
        PATENTE = "patente", "Patente"

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    type = models.CharField("Type", max_length=30, choices=DocType.choices)
    document_number = models.CharField("N° document", max_length=100, blank=True)
    issue_date = models.DateField("Date émission", null=True, blank=True)
    expiry_date = models.DateField("Date expiration", null=True, blank=True)
    file_url = models.URLField("Fichier (URL)", max_length=500, blank=True)
    file = models.FileField(
        "Fichier", upload_to="vehicles/documents/", null=True, blank=True,
    )
    status = models.CharField("Statut", max_length=20, default="valid")

    objects = TenantManager()

    class Meta:
        db_table = "fleet_vehicle_documents"
        verbose_name = "Document véhicule"
        verbose_name_plural = "Documents véhicules"

    def __str__(self):
        return f"{self.get_type_display()} — {self.vehicle.plate_number}"


class VehicleMaintenance(TenantModel):
    """Interventions de maintenance (vidange, pneus, visite technique…).

    Une ligne par intervention. On stocke en modèle dédié plutôt qu'en JSON
    sur Vehicle pour pouvoir filtrer, trier, et exposer un historique
    paginé dans la page détail DS backoffice.
    """

    class Type(models.TextChoices):
        OIL_CHANGE = "oil_change", "Vidange"
        TIRES = "tires", "Pneus"
        TECHNICAL_VISIT = "technical_visit", "Visite technique"
        BREAKDOWN = "breakdown", "Panne"
        MAJOR_SERVICE = "major_service", "Révision complète"
        OTHER = "other", "Autre"

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="maintenances",
    )
    at = models.DateField("Date d'intervention")
    type = models.CharField("Type", max_length=32, choices=Type.choices)
    odometer_km = models.PositiveIntegerField("Odomètre (km)")
    shop = models.CharField("Garage / prestataire", max_length=100, blank=True)
    cost_xof = models.PositiveIntegerField(
        "Coût (XOF)", null=True, blank=True,
    )
    notes = models.TextField("Notes", blank=True)
    created_by = models.ForeignKey(
        "iam.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Enregistré par",
    )

    objects = TenantManager()

    class Meta:
        db_table = "fleet_vehicle_maintenances"
        verbose_name = "Maintenance véhicule"
        verbose_name_plural = "Maintenances véhicules"
        ordering = ["-at", "-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.vehicle.plate_number} ({self.at})"


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
