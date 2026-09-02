from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from core.admin import TenantAdminMixin

from .models import WorkflowDefinition, WorkflowState, WorkflowTransition


class WorkflowStateInline(TabularInline):
    model = WorkflowState
    extra = 0
    ordering = ["display_order"]

class WorkflowTransitionInline(TabularInline):
    model = WorkflowTransition
    extra = 0
    fk_name = "workflow"

@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "entity_type", "tenant", "version", "is_active", "is_system"]
    list_filter = ["entity_type", "is_active", "is_system"]
    inlines = [WorkflowStateInline, WorkflowTransitionInline]

@admin.register(WorkflowState)
class WorkflowStateAdmin(TenantAdminMixin, ModelAdmin):
    # Pas de champ tenant propre : rattaché via son workflow.
    tenant_field = "workflow__tenant"

    list_display = ["workflow", "code", "label", "display_order", "is_initial", "is_terminal"]
    list_filter = ["workflow", "is_initial", "is_terminal"]
