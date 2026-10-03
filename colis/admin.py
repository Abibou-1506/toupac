"""TOUPAC Colis — Configuration Django Admin + unfold.

Enrichi au Ticket 3 : badges statut sur Order/Parcel/DeliveryTask,
list_select_related sur toutes les FK du list_display, filtres Unfold
overlay, autocomplete sur FK à grande cardinalité, fieldsets français
groupés sur OrderAdmin, date_hierarchy sur created_at.
"""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)

from core.admin import TenantAdminMixin, render_status_badge

from .models import DeliveryTask, Order, Parcel, ProofOfDelivery


class ParcelInline(TabularInline):
    model = Parcel
    extra = 0


@admin.register(Order)
class OrderAdmin(TenantAdminMixin, ModelAdmin):
    list_display = [
        "internal_id", "customer_name", "status_badge", "priority",
        "trip", "total_amount_xof", "payment_status", "created_at",
    ]
    list_select_related = ["trip", "tenant", "customer"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("priority", ChoicesDropdownFilter),
        ("payment_status", ChoicesDropdownFilter),
        ("trip", RelatedDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["internal_id", "customer_name", "customer_phone"]
    autocomplete_fields = ["trip"]
    date_hierarchy = "created_at"
    inlines = [ParcelInline]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("internal_id", "status", "priority")}),
        ("Client", {"fields": ("customer", "customer_name", "customer_phone")}),
        ("Livraison", {"fields": ("trip", "pickup_place", "dropoff_place")}),
        ("Prix", {"fields": ("total_amount_xof", "payment_status")}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(Parcel)
class ParcelAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["tracking_number", "order", "category", "weight_kg", "status_badge"]
    list_select_related = ["order", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("category", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["tracking_number", "description"]
    autocomplete_fields = ["order"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(DeliveryTask)
class DeliveryTaskAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["order", "type", "driver", "status_badge", "sequence_order"]
    list_select_related = ["order", "driver", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("type", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    autocomplete_fields = ["order", "driver"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(ProofOfDelivery)
class ProofOfDeliveryAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["delivery_task", "type", "recipient_name", "created_at"]
    list_select_related = ["delivery_task", "tenant"]
    list_filter = [("type", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    readonly_fields = ["created_at", "updated_at"]
