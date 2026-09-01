"""Seed des 3 workflows système (tenant=NULL, is_system=True)."""
from django.core.management.base import BaseCommand
from django.db import transaction

from workflow.models import WorkflowDefinition, WorkflowState, WorkflowTransition

WORKFLOWS = {
    "trip": {
        "name": "Voyage passagers standard",
        "states": [
            (1, "scheduled", "Programmé", "#6B7280", True, False),
            (2, "preparing", "Préparation", "#8B5CF6", False, False),
            (3, "boarding", "Embarquement", "#8B5CF6", False, False),
            (4, "in_transit", "En route", "#0D9488", False, False),
            (5, "at_stop", "À l'escale", "#0D9488", False, False),
            (6, "arriving", "Arrivée", "#0D9488", False, False),
            (7, "completed", "Terminé", "#059669", False, True),
            (8, "cancelled", "Annulé", "#DC2626", False, True),
        ],
        "transitions": [
            ("scheduled", "preparing", "manual"),
            ("preparing", "boarding", "on_event"),
            ("boarding", "in_transit", "manual"),
            ("in_transit", "at_stop", "automatic"),
            ("at_stop", "in_transit", "manual"),
            ("at_stop", "arriving", "on_condition"),
            ("arriving", "completed", "manual"),
            ("scheduled", "cancelled", "manual"),
            ("preparing", "cancelled", "manual"),
            ("boarding", "cancelled", "manual"),
        ],
    },
    "order": {
        "name": "Commande colis",
        "states": [
            (1, "draft", "Brouillon", "#6B7280", True, False),
            (2, "confirmed", "Confirmée", "#2563EB", False, False),
            (3, "dispatched", "Dispatchée", "#8B5CF6", False, False),
            (4, "picked_up", "Enlevée", "#0D9488", False, False),
            (5, "in_transit", "En transit", "#0D9488", False, False),
            (6, "delivered", "Livrée", "#059669", False, True),
            (7, "failed", "Échouée", "#DC2626", False, True),
            (8, "cancelled", "Annulée", "#DC2626", False, True),
        ],
        "transitions": [
            ("draft", "confirmed", "manual"),
            ("confirmed", "dispatched", "automatic"),
            ("dispatched", "picked_up", "manual"),
            ("picked_up", "in_transit", "automatic"),
            ("in_transit", "delivered", "on_event"),
            ("in_transit", "failed", "manual"),
            ("draft", "cancelled", "manual"),
            ("confirmed", "cancelled", "manual"),
            ("dispatched", "cancelled", "manual"),
        ],
    },
    "delivery_task": {
        "name": "Tâche livraison",
        "states": [
            (1, "pending", "En attente", "#6B7280", True, False),
            (2, "assigned", "Assignée", "#2563EB", False, False),
            (3, "accepted", "Acceptée", "#8B5CF6", False, False),
            (4, "en_route", "En route", "#0D9488", False, False),
            (5, "arrived", "Arrivé", "#0D9488", False, False),
            (6, "completed", "Terminée", "#059669", False, True),
            (7, "failed", "Échouée", "#DC2626", False, True),
        ],
        "transitions": [
            ("pending", "assigned", "automatic"),
            ("assigned", "accepted", "manual"),
            ("accepted", "en_route", "manual"),
            ("en_route", "arrived", "automatic"),
            ("arrived", "completed", "on_event"),
            ("assigned", "failed", "manual"),
            ("accepted", "failed", "manual"),
            ("en_route", "failed", "manual"),
            ("arrived", "failed", "manual"),
        ],
    },
}


class Command(BaseCommand):
    help = "Crée les 3 workflows système (trip, order, delivery_task), idempotent."

    def handle(self, *args, **options):
        for entity_type, spec in WORKFLOWS.items():
            self._seed_workflow(entity_type, spec)

    def _seed_workflow(self, entity_type, spec):
        label = "".join(word.capitalize() for word in entity_type.split("_"))

        workflow, created = WorkflowDefinition.objects.get_or_create(
            tenant=None,
            entity_type=entity_type,
            defaults={
                "name": spec["name"],
                "is_active": True,
                "is_system": True,
            },
        )
        if not created:
            self.stdout.write(f"Workflow {label} existe déjà")
            return

        with transaction.atomic():
            states_by_code = {}
            for display_order, code, state_label, color, is_initial, is_terminal in spec["states"]:
                states_by_code[code] = WorkflowState.objects.create(
                    workflow=workflow,
                    code=code,
                    label=state_label,
                    color=color,
                    display_order=display_order,
                    is_initial=is_initial,
                    is_terminal=is_terminal,
                )

            for from_code, to_code, trigger in spec["transitions"]:
                WorkflowTransition.objects.create(
                    workflow=workflow,
                    from_state=states_by_code[from_code],
                    to_state=states_by_code[to_code],
                    trigger=trigger,
                )

        self.stdout.write(self.style.SUCCESS(
            f"Workflow {label} créé ({len(spec['states'])} états, {len(spec['transitions'])} transitions)"
        ))
