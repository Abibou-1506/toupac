"""TOUPAC Billing — Configuration Django Admin + unfold.

Enrichi au Ticket 3 : badges statut sur Invoice/Payment,
list_select_related, filtres Unfold overlay, autocomplete sur Payment,
fieldsets français sur InvoiceAdmin, date_hierarchy sur issue_date et
initiated_at.
"""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from core.admin import RoleRestrictedAdminMixin, TenantAdminMixin, render_status_badge

from .models import Invoice, InvoiceLine, Payment, PriceList, PriceRule


class PriceRuleInline(TabularInline):
    model = PriceRule
    extra = 0


class InvoiceLineInline(TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(PriceList)
class PriceListAdmin(TenantAdminMixin, RoleRestrictedAdminMixin, ModelAdmin):
    # Ticket 4 Gamma : écran financier réservé à ADMIN compagnie + SUPERADMIN
    # TOUPAC. DISPATCHER / AGENT / CONTROLLER reçoivent 403 et l'item sidebar
    # est masqué par iam.unfold.is_admin_or_superadmin.
    allowed_tenant_roles = ("admin",)
    list_display = ["name", "type", "currency", "is_active", "tenant"]
    list_select_related = ["tenant"]
    list_filter = [
        ("type", ChoicesDropdownFilter),
        "is_active",
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["name"]
    inlines = [PriceRuleInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Invoice)
class InvoiceAdmin(TenantAdminMixin, RoleRestrictedAdminMixin, ModelAdmin):
    # Ticket 4 Gamma : voir note PriceListAdmin.
    allowed_tenant_roles = ("admin",)
    list_display = ["invoice_number", "customer_name", "total_xof", "status_badge", "issue_date"]
    list_select_related = ["tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("issue_date", RangeDateFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["invoice_number", "customer_name"]
    date_hierarchy = "issue_date"
    inlines = [InvoiceLineInline]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("invoice_number", "status", "currency")}),
        ("Client", {"fields": ("customer_id", "customer_type", "customer_name")}),
        ("Dates", {"fields": ("issue_date", "due_date", "paid_at")}),
        ("Montants", {"fields": ("subtotal_xof", "tax_xof", "total_xof")}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(Payment)
class PaymentAdmin(TenantAdminMixin, RoleRestrictedAdminMixin, ModelAdmin):
    # Ticket 4 Gamma : voir note PriceListAdmin.
    allowed_tenant_roles = ("admin",)
    list_display = [
        "provider", "amount_xof", "status_badge", "provider_tx_id",
        "reservation", "order", "initiated_at",
    ]
    list_select_related = ["reservation", "order", "invoice", "tenant"]
    list_filter = [
        ("provider", ChoicesDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["provider_tx_id"]
    autocomplete_fields = ["reservation", "order"]
    date_hierarchy = "initiated_at"
    # initiated_at est auto_now_add — Django le pose. On l'ajoute à readonly
    # pour que l'édition d'un paiement existant ne tente pas de l'écraser.
    readonly_fields = ["initiated_at"]

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())
