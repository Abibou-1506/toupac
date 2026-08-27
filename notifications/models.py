"""TOUPAC Notifications — Templates de messages et historique d'envoi."""
from django.db import models
from core.models import TenantModel, TenantManager


class NotificationTemplate(TenantModel):
    """Modèle de message par événement, canal et langue. tenant=NULL → système."""
    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        PUSH = "push", "Push"
        EMAIL = "email", "Email"

    tenant = models.ForeignKey(
        "iam.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="notification_templates",
    )
    event_type = models.CharField("Type d'événement", max_length=50)
    channel = models.CharField("Canal", max_length=10, choices=Channel.choices)
    language = models.CharField("Langue", max_length=2, default="fr")
    subject = models.CharField("Sujet", max_length=200, blank=True)
    template_body = models.TextField("Corps du message")
    is_active = models.BooleanField("Actif", default=True)

    objects = TenantManager()

    class Meta:
        db_table = "notifications_templates"
        verbose_name = "Template de notification"
        verbose_name_plural = "Templates de notification"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "event_type", "channel", "language"],
                name="unique_template_per_tenant_event_channel_lang",
            ),
        ]

    def __str__(self):
        return f"{self.event_type} / {self.channel} / {self.language}"


class NotificationLog(TenantModel):
    """Historique des notifications envoyées."""
    class Status(models.TextChoices):
        QUEUED = "queued", "En file"
        SENT = "sent", "Envoyée"
        DELIVERED = "delivered", "Livrée"
        FAILED = "failed", "Échouée"

    user = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="notification_logs",
    )
    channel = models.CharField("Canal", max_length=10)
    recipient = models.CharField("Destinataire", max_length=100)
    event_type = models.CharField("Type d'événement", max_length=50)
    content = models.TextField("Contenu", blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider = models.CharField("Provider", max_length=30, blank=True)
    provider_message_id = models.CharField("ID message provider", max_length=100, blank=True)
    failure_reason = models.CharField("Motif d'échec", max_length=300, blank=True)
    sent_at = models.DateTimeField("Envoyée à", null=True, blank=True)
    delivered_at = models.DateTimeField("Livrée à", null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "notifications_logs"
        verbose_name = "Log de notification"
        verbose_name_plural = "Logs de notification"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} → {self.recipient} ({self.get_status_display()})"
