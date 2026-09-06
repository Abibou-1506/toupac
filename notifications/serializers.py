"""TOUPAC Notifications — Serializers DRF."""
from rest_framework import serializers

from .models import NotificationLog, NotificationTemplate


class NotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = "__all__"


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = "__all__"
        read_only_fields = [f.name for f in NotificationLog._meta.fields]


class SendNotificationSerializer(serializers.Serializer):
    event_code = serializers.CharField(max_length=100)
    channel = serializers.ChoiceField(choices=NotificationTemplate.Channel.choices)
    recipient = serializers.CharField(max_length=100)
    context_data = serializers.JSONField()
    language = serializers.CharField(max_length=2, default="fr")
