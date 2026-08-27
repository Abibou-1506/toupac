"""TOUPAC Workflow — ViewSets et vues DRF."""
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import WorkflowDefinition
from .serializers import (
    WorkflowCurrentStateSerializer, WorkflowDefinitionDetailSerializer,
    WorkflowDefinitionListSerializer,
)


@extend_schema_view(list=extend_schema(tags=["Workflow"]), retrieve=extend_schema(tags=["Workflow"]))
class WorkflowDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkflowDefinition.objects.none()
    filterset_fields = ["entity_type", "is_active"]

    def get_queryset(self):
        # Workflows du tenant + workflows système (tenant=NULL).
        return (
            WorkflowDefinition.objects.filter(
                Q(tenant=self.request.tenant) | Q(tenant__isnull=True),
            )
            .select_related("tenant")
            .prefetch_related("states", "transitions__from_state", "transitions__to_state")
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return WorkflowDefinitionDetailSerializer
        return WorkflowDefinitionListSerializer


@extend_schema(
    tags=["Workflow"],
    responses={
        200: WorkflowCurrentStateSerializer,
        404: inline_serializer("EntityWorkflowNotFound", {"detail": serializers.CharField()}),
    },
)
class EntityWorkflowView(APIView):
    """GET /api/v1/workflows/{entity_type}/{entity_id}/current-state/"""

    def get(self, request, entity_type, entity_id):
        entity = None
        if entity_type == "trip":
            from voyage.models import Trip
            entity = Trip.objects.filter(id=entity_id, tenant=request.tenant).first()
        elif entity_type == "order":
            from colis.models import Order
            entity = Order.objects.filter(id=entity_id, tenant=request.tenant).first()
        elif entity_type == "delivery_task":
            from colis.models import DeliveryTask
            entity = DeliveryTask.objects.filter(id=entity_id, tenant=request.tenant).first()

        if not entity:
            return Response({"detail": "Entité non trouvée."}, status=status.HTTP_404_NOT_FOUND)

        workflow = (
            WorkflowDefinition.objects.filter(entity_type=entity_type, is_active=True)
            .filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
            .order_by("-tenant_id")  # tenant-specific prioritaire sur système
            .first()
        )

        if not workflow:
            return Response({"detail": "Aucun workflow configuré."}, status=status.HTTP_404_NOT_FOUND)

        current_state = workflow.states.filter(code=entity.status).first()

        available = []
        if current_state:
            transitions = workflow.transitions.filter(from_state=current_state).select_related("to_state")
            available = [
                {"to_state": {"code": t.to_state.code, "label": t.to_state.label}, "trigger": t.trigger}
                for t in transitions
            ]

        data = {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "current_state": current_state,
            "available_transitions": available,
        }
        return Response(WorkflowCurrentStateSerializer(data).data)
