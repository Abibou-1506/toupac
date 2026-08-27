"""TOUPAC Notifications — Configuration Django Admin + unfold."""
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import NotificationLog, NotificationTemplate


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(ModelAdmin):
    list_display = ["event_type", "channel", "language", "is_active", "tenant"]
    list_filter = ["channel", "is_active", "event_type"]


@admin.register(NotificationLog)
class NotificationLogAdmin(ModelAdmin):
    list_display = ["event_type", "channel", "recipient", "status", "provider", "sent_at"]
    list_filter = ["channel", "status", "event_type"]
    readonly_fields = [f.name for f in NotificationLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
