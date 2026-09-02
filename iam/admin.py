"""TOUPAC IAM — Configuration Django Admin + unfold."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin

from core.admin import SuperadminOnlyAdminMixin, TenantAdminMixin

from .models import ApiCredential, AuditLog, Tenant, User, UserDevice


@admin.register(Tenant)
class TenantAdmin(SuperadminOnlyAdminMixin, ModelAdmin):
    """Tenant est la racine : il n'a pas de tenant. Réservé aux superadmins."""
    list_display = ["name", "country_code", "currency", "status", "subscription_plan", "created_at"]
    list_filter = ["status", "country_code", "subscription_plan"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]


@admin.register(User)
class UserAdmin(TenantAdminMixin, BaseUserAdmin, ModelAdmin):
    list_display = ["email", "first_name", "last_name", "role", "tenant", "is_active"]
    list_filter = ["role", "is_active", "tenant"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["last_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informations", {"fields": ("first_name", "last_name", "phone", "tenant", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login_at", "created_at", "updated_at", "deleted_at")}),
    )
    readonly_fields = ["created_at", "updated_at", "last_login_at"]
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "tenant", "role", "password1", "password2"),
        }),
    )


@admin.register(ApiCredential)
class ApiCredentialAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "tenant", "key_prefix", "is_active", "last_used_at"]
    list_filter = ["is_active", "tenant"]


@admin.register(AuditLog)
class AuditLogAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["action", "resource_type", "user", "tenant", "created_at"]
    list_filter = ["action", "resource_type"]
    readonly_fields = ["id", "tenant", "user", "action", "resource_type", "resource_id", "changes", "ip_address", "created_at"]
    search_fields = ["resource_type", "action"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(UserDevice)
class UserDeviceAdmin(TenantAdminMixin, ModelAdmin):
    # Pas de champ tenant propre : rattaché via son utilisateur.
    tenant_field = "user__tenant"

    list_display = ["user", "platform", "device_model", "is_active"]
    list_filter = ["platform", "is_active"]
