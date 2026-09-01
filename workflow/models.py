"""
TOUPAC Workflow — Machine à états configurable multi-tenant.
Remplace le OrderConfig.flow JSONB de Fleetbase.
"""
from django.db import models

from core.models import TimestampMixin, UUIDv7Field


class WorkflowDefinition(TimestampMixin, models.Model):
    """Un workflow par (tenant, entity_type). tenant=NULL → workflow système."""
    class EntityType(models.TextChoices):
        TRIP = "trip", "Voyage"
        ORDER = "order", "Commande colis"
        DELIVERY_TASK = "delivery_task", "Tâche livraison"
        PARCEL = "parcel", "Colis"
        INCIDENT = "incident", "Incident"

    id = UUIDv7Field()
    tenant = models.ForeignKey(
        "iam.Tenant", on_delete=models.CASCADE, null=True, blank=True,
        related_name="workflows", verbose_name="Tenant",
    )
    entity_type = models.CharField("Type d'entité", max_length=30, choices=EntityType.choices)
    name = models.CharField("Nom", max_length=100)
    description = models.TextField("Description", blank=True)
    version = models.PositiveIntegerField("Version", default=1)
    is_active = models.BooleanField("Actif", default=True)
    is_system = models.BooleanField("Système (non supprimable)", default=False)
    created_by = models.ForeignKey(
        "iam.User", on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        db_table = "workflow_definitions"
        verbose_name = "Workflow"
        verbose_name_plural = "Workflows"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "entity_type"],
                condition=models.Q(is_active=True),
                name="unique_active_workflow_per_tenant_entity",
            ),
        ]

    def __str__(self):
        scope = self.tenant.name if self.tenant else "SYSTÈME"
        return f"{self.name} ({scope}, v{self.version})"


class WorkflowState(TimestampMixin, models.Model):
    """État/activité dans un workflow. display_order = linéaire (stepper UI)."""
    id = UUIDv7Field()
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="states")
    code = models.CharField("Code", max_length=30)
    label = models.CharField("Label", max_length=50)
    color = models.CharField("Couleur (hex)", max_length=7, default="#6B7280")
    display_order = models.PositiveSmallIntegerField("Ordre affichage")
    is_initial = models.BooleanField("État initial", default=False)
    is_terminal = models.BooleanField("État terminal", default=False)
    config = models.JSONField("Configuration", default=dict, blank=True)

    class Meta:
        db_table = "workflow_states"
        verbose_name = "État workflow"
        verbose_name_plural = "États workflow"
        ordering = ["display_order"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "code"], name="unique_state_code_per_workflow"),
            models.UniqueConstraint(fields=["workflow", "display_order"], name="unique_display_order_per_workflow"),
        ]

    def __str__(self):
        return f"{self.code} — {self.label}"


class WorkflowTransition(TimestampMixin, models.Model):
    """Transition autorisée entre deux états."""
    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manuel"
        AUTOMATIC = "automatic", "Automatique"
        ON_EVENT = "on_event", "Sur événement"
        ON_CONDITION = "on_condition", "Sur condition"

    id = UUIDv7Field()
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.ForeignKey(WorkflowState, on_delete=models.CASCADE, related_name="transitions_out")
    to_state = models.ForeignKey(WorkflowState, on_delete=models.CASCADE, related_name="transitions_in")
    trigger = models.CharField("Déclencheur", max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    event_type = models.CharField("Type d'événement", max_length=50, blank=True)
    guard = models.JSONField("Conditions", default=dict, blank=True)
    priority = models.PositiveSmallIntegerField("Priorité", default=0)

    class Meta:
        db_table = "workflow_transitions"
        verbose_name = "Transition"
        verbose_name_plural = "Transitions"
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "from_state", "to_state"],
                name="unique_transition_per_workflow",
            ),
        ]

    def __str__(self):
        return f"{self.from_state.code} → {self.to_state.code}"


class WorkflowHook(TimestampMixin, models.Model):
    """Side-effect déclenché lors d'une transition."""
    class HookType(models.TextChoices):
        NOTIFY = "notify", "Notification"
        UPDATE_FIELD = "update_field", "Mise à jour champ"
        WEBHOOK = "webhook", "Webhook"
        CELERY_TASK = "celery_task", "Tâche Celery"

    id = UUIDv7Field()
    transition = models.ForeignKey(WorkflowTransition, on_delete=models.CASCADE, related_name="hooks")
    hook_type = models.CharField("Type", max_length=20, choices=HookType.choices)
    config = models.JSONField("Configuration")
    execution_order = models.PositiveSmallIntegerField("Ordre exécution", default=0)

    class Meta:
        db_table = "workflow_hooks"
        verbose_name = "Hook"
        verbose_name_plural = "Hooks"
        ordering = ["execution_order"]

    def __str__(self):
        return f"{self.get_hook_type_display()} (transition: {self.transition})"
