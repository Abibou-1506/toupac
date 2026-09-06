"""TOUPAC Notifications — Configuration Django Admin + unfold."""
from django.contrib import admin
from unfold.admin import ModelAdmin

from core.admin import TenantAdminMixin

from .models import Notification, NotificationLog, NotificationTemplate


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["event_code", "channel", "language", "is_active", "tenant"]
    list_filter = ["channel", "is_active", "event_code"]


@admin.register(Notification)
class NotificationAdmin(TenantAdminMixin, ModelAdmin):
    """Lecture seule côté création : les notifications naissent du service (Ticket B).

    Change et delete restent ouverts pour le diagnostic, mais le mixin les
    restreint déjà au tenant de l'utilisateur — un admin de compagnie ne voit
    et ne touche que les siennes.
    """
    list_display = ["event_code", "recipient_user", "priority", "trigger_scope", "read_at", "created_at"]
    list_filter = ["priority", "trigger_scope", "event_code"]
    search_fields = ["event_code", "title", "idempotency_key"]
    ordering = ["-created_at"]
    readonly_fields = ["created_at", "updated_at"]

    def has_add_permission(self, request):
        return False


@admin.register(NotificationLog)
class NotificationLogAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["event_code", "channel", "recipient", "status", "provider", "sent_at"]
    list_filter = ["channel", "status", "event_code"]
    readonly_fields = [f.name for f in NotificationLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
