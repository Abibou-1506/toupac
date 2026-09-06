"""TOUPAC Notifications — Templates de messages et historique d'envoi."""
from django.db import models

from core.models import TenantManager, TenantModel


class NotificationTemplate(TenantModel):
    """Modèle de message par événement, canal et langue. tenant=NULL → système."""
    class Channel(models.TextChoices):
        # Ordre aligné sur la charte TOUPAC ONE : canaux OBLIGATOIRES d'abord
        # (Push, In-app / back-office), puis SELON CAS (Email), puis OTP-only.
        PUSH = "push", "Push"
        IN_APP = "in_app", "In-app / back-office"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    tenant = models.ForeignKey(
        "iam.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="notification_templates",
    )
    event_code = models.CharField("Code d'événement", max_length=100, db_index=True)
    channel = models.CharField("Canal", max_length=10, choices=Channel.choices)
    language = models.CharField("Langue", max_length=2, default="fr")
    title_template = models.CharField(
        "Titre (gabarit)", max_length=200, blank=True,
        help_text="Rendu pour le titre push (≤45 caractères après rendu), l'item in-app et le sujet e-mail.",
    )
    template_body = models.TextField("Corps du message")
    action_url_template = models.CharField(
        "URL d'action (gabarit)", max_length=500, blank=True,
        help_text="CTA du message, rendu comme un gabarit Django.",
    )
    is_active = models.BooleanField("Actif", default=True)

    objects = TenantManager()

    class Meta:
        db_table = "notifications_templates"
        verbose_name = "Template de notification"
        verbose_name_plural = "Templates de notification"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "event_code", "channel", "language"],
                name="unique_template_per_tenant_event_channel_lang",
            ),
        ]

    def __str__(self):
        return f"{self.event_code} / {self.channel} / {self.language}"


class Notification(TenantModel):
    """Item du centre d'alertes, lisible par un utilisateur unique.

    Une Notification = UN destinataire. Un événement diffusé à un rôle produit N
    lignes, une par utilisateur résolu — c'est ce qui rend `read_at` / `acked_at`
    individuels. `trigger_scope` et `trigger_role` gardent la trace de l'origine
    de la diffusion (audit, filtres, « cette alerte visait tous les dispatchers ») ;
    ils ne servent jamais à rejouer la résolution.
    """
    class Priority(models.TextChoices):
        CRITICAL = "critical", "Critique"
        HIGH = "high", "Haute"
        MEDIUM = "medium", "Moyenne"
        LOW = "low", "Basse"

    class TriggerScope(models.TextChoices):
        USER = "user", "Utilisateur individuel"
        ROLE = "role", "Broadcast rôle"
        TENANT = "tenant", "Broadcast tenant"

    event_code = models.CharField("Code d'événement", max_length=100, db_index=True)
    recipient_user = models.ForeignKey(
        "iam.User", on_delete=models.CASCADE, related_name="notifications", verbose_name="Destinataire",
    )
    trigger_scope = models.CharField("Portée d'émission", max_length=10, choices=TriggerScope.choices)
    trigger_role = models.CharField(
        "Rôle visé", max_length=20, blank=True, help_text="Rôle destinataire si trigger_scope=role",
    )
    priority = models.CharField("Priorité", max_length=10, choices=Priority.choices)
    title = models.CharField("Titre", max_length=200)
    body = models.TextField("Corps")
    action_url = models.CharField("URL d'action", max_length=500, blank=True)
    read_at = models.DateTimeField("Lue à", null=True, blank=True)
    acked_at = models.DateTimeField(
        "Accusée à", null=True, blank=True, help_text="Pour les événements avec requires_ack",
    )
    expires_at = models.DateTimeField("Expire à", null=True, blank=True)
    idempotency_key = models.CharField(
        "Clé d'idempotence", max_length=100, blank=True, db_index=True,
        help_text="Calculée par le service (Ticket B) : {event_code}:{actor_id}:{target_hash}",
    )

    objects = TenantManager()

    class Meta:
        db_table = "notifications_notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            # Le queryset par défaut du centre d'alertes : mes notifs non lues.
            models.Index(fields=["tenant", "recipient_user", "read_at"]),
            models.Index(fields=["tenant", "event_code", "created_at"]),
            models.Index(fields=["tenant", "idempotency_key"]),
        ]
        constraints = [
            # Idempotence N-06 garantie en base, pas seulement dans le service.
            # Partielle : une clé vide signifie « pas d'idempotence demandée » et
            # ne doit pas faire collisionner deux notifications légitimes.
            models.UniqueConstraint(
                fields=["tenant", "recipient_user", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="unique_notification_idempotency_per_tenant_user",
            ),
        ]

    def __str__(self):
        return f"{self.event_code} → {self.recipient_user_id}"


class NotificationLog(TenantModel):
    """Historique des tentatives d'envoi, tous canaux confondus."""
    class Status(models.TextChoices):
        QUEUED = "queued", "En file"
        SENT = "sent", "Envoyée"
        DELIVERED = "delivered", "Livrée"
        FAILED = "failed", "Échouée"

    user = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="notification_logs",
    )
    notification = models.ForeignKey(
        Notification, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_attempts",
        verbose_name="Notification",
        help_text="Item de centre d'alertes associé, s'il y en a un. Reste vide pour les envois "
                  "sans contrepartie in-app (OTP SMS, par exemple).",
    )
    channel = models.CharField("Canal", max_length=10)
    recipient = models.CharField("Destinataire", max_length=100)
    event_code = models.CharField("Code d'événement", max_length=100)
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
        return f"{self.event_code} → {self.recipient} ({self.get_status_display()})"
