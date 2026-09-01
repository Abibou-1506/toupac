"""TOUPAC Billing — Grilles tarifaires, factures et paiements mobile money."""
from django.db import models

from core.models import TenantManager, TenantModel, UUIDv7Field


class PriceList(TenantModel):
    """Grille tarifaire (par tenant, par module)."""
    class Type(models.TextChoices):
        VOYAGE = "voyage", "Voyage"
        COLIS = "colis", "Colis"

    name = models.CharField("Nom", max_length=100)
    type = models.CharField("Type", max_length=20, choices=Type.choices)
    currency = models.CharField("Devise", max_length=3, default="XOF")
    is_active = models.BooleanField("Active", default=True)
    valid_from = models.DateField("Valide à partir de", null=True, blank=True)
    valid_until = models.DateField("Valide jusqu'à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "billing_price_lists"
        verbose_name = "Grille tarifaire"
        verbose_name_plural = "Grilles tarifaires"

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class PriceRule(TenantModel):
    """Règle tarifaire au sein d'une grille."""
    class CalculationMethod(models.TextChoices):
        FIXED = "fixed", "Forfait"
        PER_KM = "per_km", "Par km"
        PER_KG = "per_kg", "Par kg"
        PER_ZONE = "per_zone", "Par zone"

    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="rules")
    route = models.ForeignKey(
        "voyage.Route", on_delete=models.SET_NULL, null=True, blank=True, related_name="price_rules",
    )
    origin_zone = models.ForeignKey(
        "geo.Zone", on_delete=models.SET_NULL, null=True, blank=True, related_name="price_rules_origin",
    )
    destination_zone = models.ForeignKey(
        "geo.Zone", on_delete=models.SET_NULL, null=True, blank=True, related_name="price_rules_dest",
    )
    calculation_method = models.CharField(
        "Méthode de calcul", max_length=20, choices=CalculationMethod.choices, default=CalculationMethod.FIXED,
    )
    base_amount_xof = models.IntegerField("Montant de base (XOF)")
    rate_per_unit = models.DecimalField(
        "Taux par unité", max_digits=10, decimal_places=2, null=True, blank=True,
    )
    min_amount_xof = models.IntegerField("Montant minimum (XOF)", null=True, blank=True)
    max_amount_xof = models.IntegerField("Montant maximum (XOF)", null=True, blank=True)
    conditions = models.JSONField("Conditions", default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "billing_price_rules"
        verbose_name = "Règle tarifaire"
        verbose_name_plural = "Règles tarifaires"

    def __str__(self):
        return f"{self.get_calculation_method_display()} — {self.base_amount_xof} XOF"


class Invoice(TenantModel):
    """Facture — client inscrit ou externe, voyage ou colis."""
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        SENT = "sent", "Envoyée"
        PAID = "paid", "Payée"
        OVERDUE = "overdue", "En retard"
        CANCELLED = "cancelled", "Annulée"

    invoice_number = models.CharField("N° facture", max_length=20)
    customer_id = models.UUIDField("ID client", null=True, blank=True)
    customer_type = models.CharField("Type de client", max_length=20, blank=True)
    customer_name = models.CharField("Nom client", max_length=200)
    issue_date = models.DateField("Date d'émission")
    due_date = models.DateField("Date d'échéance", null=True, blank=True)
    subtotal_xof = models.IntegerField("Sous-total (XOF)")
    tax_xof = models.IntegerField("Taxes (XOF)", default=0)
    total_xof = models.IntegerField("Total (XOF)")
    currency = models.CharField("Devise", max_length=3, default="XOF")
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.DRAFT)
    paid_at = models.DateTimeField("Payée à", null=True, blank=True)
    metadata = models.JSONField("Métadonnées", default=dict, blank=True)
    created_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices_created",
    )

    objects = TenantManager()

    class Meta:
        db_table = "billing_invoices"
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "invoice_number"], name="unique_invoice_number_per_tenant"),
        ]

    def __str__(self):
        return f"Facture {self.invoice_number} — {self.total_xof} XOF"


class InvoiceLine(models.Model):
    """Ligne de facture. Pas de tenant propre — porté par la facture parente."""
    id = UUIDv7Field()
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField("Description", max_length=500)
    reference_type = models.CharField("Type de référence", max_length=20, blank=True)
    reference_id = models.UUIDField("ID de référence", null=True, blank=True)
    quantity = models.IntegerField("Quantité", default=1)
    unit_price_xof = models.IntegerField("Prix unitaire (XOF)")
    amount_xof = models.IntegerField("Montant (XOF)")
    tax_xof = models.IntegerField("Taxes (XOF)", default=0)
    created_at = models.DateTimeField("Créée à", auto_now_add=True)

    class Meta:
        db_table = "billing_invoice_lines"
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"

    def __str__(self):
        return f"{self.description} — {self.amount_xof} XOF"


class Payment(TenantModel):
    """Transaction de paiement (mobile money, espèces, virement)."""
    class Provider(models.TextChoices):
        WAVE = "wave", "Wave"
        ORANGE_MONEY = "orange_money", "Orange Money"
        FREE_MONEY = "free_money", "Free Money"
        MTN_MOMO = "mtn_momo", "MTN Mobile Money"
        CASH = "cash", "Espèces"
        BANK_TRANSFER = "bank_transfer", "Virement bancaire"

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initié"
        PENDING = "pending", "En attente"
        SUCCESS = "success", "Réussi"
        FAILED = "failed", "Échoué"
        REFUNDED = "refunded", "Remboursé"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments",
    )
    reservation = models.ForeignKey(
        "voyage.Reservation", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments",
    )
    order = models.ForeignKey(
        "colis.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments",
    )
    provider = models.CharField("Provider", max_length=20, choices=Provider.choices)
    provider_tx_id = models.CharField("ID transaction provider", max_length=100, blank=True)
    amount_xof = models.IntegerField("Montant (XOF)")
    currency = models.CharField("Devise", max_length=3, default="XOF")
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.INITIATED)
    failure_reason = models.CharField("Motif d'échec", max_length=300, blank=True)
    provider_response = models.JSONField("Réponse provider", default=dict, blank=True)
    initiated_at = models.DateTimeField("Initié à", auto_now_add=True)
    completed_at = models.DateTimeField("Terminé à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "billing_payments"
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"

    def __str__(self):
        return f"Paiement {self.get_provider_display()} — {self.amount_xof} XOF ({self.get_status_display()})"
