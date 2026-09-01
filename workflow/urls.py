from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EntityWorkflowView, WorkflowDefinitionViewSet

router = DefaultRouter()
router.register("definitions", WorkflowDefinitionViewSet, basename="workflow-definition")

urlpatterns = [
    *router.urls,
    path("<str:entity_type>/<uuid:entity_id>/current-state/", EntityWorkflowView.as_view(), name="entity-current-state"),
]
