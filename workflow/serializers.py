"""TOUPAC Workflow — Serializers DRF."""
from rest_framework import serializers

from iam.models import Tenant

from .models import WorkflowDefinition, WorkflowHook, WorkflowState, WorkflowTransition


class WorkflowStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowState
        fields = ["id", "code", "label", "color", "display_order", "is_initial", "is_terminal", "config"]


class WorkflowStateMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowState
        fields = ["code", "label"]


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    from_state = WorkflowStateMiniSerializer(read_only=True)
    to_state = WorkflowStateMiniSerializer(read_only=True)

    class Meta:
        model = WorkflowTransition
        fields = ["id", "from_state", "to_state", "trigger", "event_type", "guard", "priority"]


class WorkflowHookSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowHook
        fields = ["id", "hook_type", "config", "execution_order"]


class WorkflowTenantMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name"]


class WorkflowDefinitionListSerializer(serializers.ModelSerializer):
    tenant = WorkflowTenantMiniSerializer(read_only=True)

    class Meta:
        model = WorkflowDefinition
        fields = ["id", "entity_type", "name", "version", "is_active", "is_system", "tenant"]


class WorkflowDefinitionDetailSerializer(WorkflowDefinitionListSerializer):
    states = WorkflowStateSerializer(many=True, read_only=True)
    transitions = WorkflowTransitionSerializer(many=True, read_only=True)

    class Meta(WorkflowDefinitionListSerializer.Meta):
        fields = [*WorkflowDefinitionListSerializer.Meta.fields, "description", "states", "transitions"]


class AvailableTransitionSerializer(serializers.Serializer):
    to_state = serializers.DictField()
    trigger = serializers.CharField()


class WorkflowCurrentStateSerializer(serializers.Serializer):
    """Serializer custom — état courant + transitions disponibles pour une entité."""
    entity_type = serializers.CharField()
    entity_id = serializers.CharField()
    current_state = WorkflowStateSerializer(allow_null=True)
    available_transitions = AvailableTransitionSerializer(many=True)
