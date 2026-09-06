"""TOUPAC Notifications — ViewSets et vues DRF."""
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationLog, NotificationTemplate
from .serializers import (
    NotificationLogSerializer,
    NotificationTemplateSerializer,
    SendNotificationSerializer,
)
from .tasks import send_notification_async

_TAG = extend_schema(tags=["Notifications"])


@extend_schema_view(
    list=_TAG, retrieve=_TAG, create=_TAG, update=_TAG, partial_update=_TAG, destroy=_TAG,
)
class NotificationTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationTemplateSerializer
    queryset = NotificationTemplate.objects.none()
    filterset_fields = ["event_code", "channel", "is_active"]

    def get_queryset(self):
        return NotificationTemplate.objects.filter(
            Q(tenant=self.request.tenant) | Q(tenant__isnull=True),
        )


@extend_schema_view(list=_TAG, retrieve=_TAG)
class NotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationLogSerializer
    queryset = NotificationLog.objects.none()
    filterset_fields = ["channel", "event_code", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return NotificationLog.objects.filter(tenant=self.request.tenant)


@extend_schema(
    tags=["Notifications"],
    request=SendNotificationSerializer,
    responses=inline_serializer("SendNotificationResponse", {"detail": serializers.CharField()}),
)
class SendNotificationView(APIView):
    """POST /api/v1/notifications/send/ — envoi manuel (dispatcher/admin)."""

    def post(self, request):
        serializer = SendNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        send_notification_async.delay(
            tenant_id=str(request.tenant.id),
            event_code=data["event_code"],
            channel=data["channel"],
            recipient=data["recipient"],
            context_data=data["context_data"],
            language=data.get("language", "fr"),
        )
        return Response({"detail": "Notification en cours d'envoi."}, status=status.HTTP_202_ACCEPTED)
