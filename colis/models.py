"""TOUPAC Colis — Commandes de livraison, colis, tâches et preuves de livraison."""
from django.contrib.gis.db import models
from core.models import TenantModel, TenantManager, SoftDeleteMixin


class Order(TenantModel, SoftDeleteMixin):
    """Commande de livraison — peut contenir plusieurs colis."""
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        CONFIRMED = "confirmed", "Confirmée"
        DISPATCHED = "dispatched", "Dispatchée"
        PICKED_UP = "picked_up", "Enlevée"
        IN_TRANSIT = "in_transit", "En transit"
        DELIVERED = "delivered", "Livrée"
        FAILED = "failed", "Échouée"
        CANCELLED = "cancelled", "Annulée"

    class Priority(models.TextChoices):
        STANDARD = "standard", "Standard"
        EXPRESS = "express", "Express"
        URGENT = "urgent", "Urgent"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        PAID = "paid", "Payé"
        REFUNDED = "refunded", "Remboursé"

    internal_id = models.CharField("Identifiant interne", max_length=20)
    customer = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders",
    )
    customer_name = models.CharField("Nom client", max_length=200, blank=True)
    customer_phone = models.CharField("Téléphone client", max_length=20, blank=True)
    pickup_place = models.ForeignKey(
        "geo.Place", on_delete=models.PROTECT, related_name="pickup_orders", verbose_name="Lieu d'enlèvement",
    )
    dropoff_place = models.ForeignKey(
        "geo.Place", on_delete=models.PROTECT, related_name="dropoff_orders", verbose_name="Lieu de livraison",
    )
    pickup_window_start = models.DateTimeField("Fenêtre enlèvement — début", null=True, blank=True)
    pickup_window_end = models.DateTimeField("Fenêtre enlèvement — fin", null=True, blank=True)
    delivery_window_start = models.DateTimeField("Fenêtre livraison — début", null=True, blank=True)
    delivery_window_end = models.DateTimeField("Fenêtre livraison — fin", null=True, blank=True)
    priority = models.CharField("Priorité", max_length=20, choices=Priority.choices, default=Priority.STANDARD)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.DRAFT)
    total_amount_xof = models.IntegerField("Montant total (XOF)", null=True, blank=True)
    payment_status = models.CharField(
        "Statut paiement", max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
    )
    instructions = models.TextField("Instructions", blank=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)
    created_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_orders",
    )

    objects = TenantManager()

    class Meta:
        db_table = "colis_orders"
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "internal_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "internal_id"], name="unique_order_internal_id_per_tenant"),
        ]

    def __str__(self):
        return f"{self.internal_id} — {self.get_status_display()}"


class Parcel(TenantModel):
    """Colis individuel rattaché à une commande."""
    class Status(models.TextChoices):
        CREATED = "created", "Créé"
        PICKED_UP = "picked_up", "Enlevé"
        IN_TRANSIT = "in_transit", "En transit"
        AT_HUB = "at_hub", "Au hub"
        OUT_FOR_DELIVERY = "out_for_delivery", "En cours de livraison"
        DELIVERED = "delivered", "Livré"
        RETURNED = "returned", "Retourné"

    class Category(models.TextChoices):
        STANDARD = "standard", "Standard"
        FRAGILE = "fragile", "Fragile"
        PERISHABLE = "perishable", "Périssable"
        HAZARDOUS = "hazardous", "Dangereux"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="parcels")
    tracking_number = models.CharField("N° de suivi", max_length=20)
    description = models.CharField("Description", max_length=500, blank=True)
    weight_kg = models.DecimalField("Poids (kg)", max_digits=8, decimal_places=2, null=True, blank=True)
    length_cm = models.DecimalField("Longueur (cm)", max_digits=6, decimal_places=1, null=True, blank=True)
    width_cm = models.DecimalField("Largeur (cm)", max_digits=6, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField("Hauteur (cm)", max_digits=6, decimal_places=1, null=True, blank=True)
    category = models.CharField("Catégorie", max_length=20, choices=Category.choices, default=Category.STANDARD)
    declared_value_xof = models.IntegerField("Valeur déclarée (XOF)", null=True, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.CREATED)

    objects = TenantManager()

    class Meta:
        db_table = "colis_parcels"
        verbose_name = "Colis"
        verbose_name_plural = "Colis"
        constraints = [
            models.UniqueConstraint(fields=["tracking_number"], name="unique_parcel_tracking_number"),
        ]

    def __str__(self):
        return f"{self.tracking_number} ({self.get_status_display()})"


class DeliveryTask(TenantModel):
    """Tâche d'enlèvement ou de livraison assignée à un chauffeur."""
    class TaskType(models.TextChoices):
        PICKUP = "pickup", "Enlèvement"
        DELIVERY = "delivery", "Livraison"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        ASSIGNED = "assigned", "Assignée"
        ACCEPTED = "accepted", "Acceptée"
        EN_ROUTE = "en_route", "En route"
        ARRIVED = "arrived", "Arrivée"
        COMPLETED = "completed", "Terminée"
        FAILED = "failed", "Échouée"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="delivery_tasks")
    driver = models.ForeignKey(
        "fleet.Driver", on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_tasks",
    )
    vehicle = models.ForeignKey(
        "fleet.Vehicle", on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_tasks",
    )
    type = models.CharField("Type", max_length=20, choices=TaskType.choices)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.PENDING)
    sequence_order = models.IntegerField("Ordre de tournée", null=True, blank=True)
    place = models.ForeignKey("geo.Place", on_delete=models.PROTECT, related_name="delivery_tasks")
    estimated_arrival = models.DateTimeField("Arrivée estimée", null=True, blank=True)
    actual_arrival = models.DateTimeField("Arrivée réelle", null=True, blank=True)
    completed_at = models.DateTimeField("Terminée à", null=True, blank=True)
    failure_reason = models.CharField("Motif d'échec", max_length=200, blank=True)
    route_geometry = models.LineStringField("Géométrie trajet", geography=True, srid=4326, null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "colis_delivery_tasks"
        verbose_name = "Tâche de livraison"
        verbose_name_plural = "Tâches de livraison"
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "driver"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} — {self.order.internal_id}"


class ProofOfDelivery(TenantModel):
    """Preuve de livraison ou d'enlèvement capturée par le chauffeur."""
    class PodType(models.TextChoices):
        SIGNATURE = "signature", "Signature"
        PHOTO = "photo", "Photo"
        QR_SCAN = "qr_scan", "Scan QR"
        OTP = "otp", "Code OTP"

    delivery_task = models.ForeignKey(DeliveryTask, on_delete=models.CASCADE, related_name="proofs")
    type = models.CharField("Type", max_length=20, choices=PodType.choices)
    signature_url = models.URLField("Signature", max_length=500, blank=True)
    photos_urls = models.JSONField("Photos", default=list, blank=True)
    otp_code = models.CharField("Code OTP", max_length=10, blank=True)
    recipient_name = models.CharField("Nom destinataire", max_length=100, blank=True)
    recipient_phone = models.CharField("Téléphone destinataire", max_length=20, blank=True)
    notes = models.TextField("Notes", blank=True)
    gps_location = models.PointField("Position GPS", geography=True, srid=4326, null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "colis_proofs_of_delivery"
        verbose_name = "Preuve de livraison"
        verbose_name_plural = "Preuves de livraison"

    def __str__(self):
        return f"POD {self.get_type_display()} — {self.delivery_task}"
