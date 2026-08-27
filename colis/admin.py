"""TOUPAC Colis — Configuration Django Admin + unfold."""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import DeliveryTask, Order, Parcel, ProofOfDelivery


class ParcelInline(TabularInline):
    model = Parcel
    extra = 0


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["internal_id", "customer_name", "status", "priority", "total_amount_xof", "payment_status", "created_at"]
    list_filter = ["status", "priority", "tenant"]
    search_fields = ["internal_id", "customer_name", "customer_phone"]
    inlines = [ParcelInline]


@admin.register(Parcel)
class ParcelAdmin(ModelAdmin):
    list_display = ["tracking_number", "order", "category", "weight_kg", "status"]
    list_filter = ["status", "category", "tenant"]
    search_fields = ["tracking_number", "description"]


@admin.register(DeliveryTask)
class DeliveryTaskAdmin(ModelAdmin):
    list_display = ["order", "type", "driver", "status", "sequence_order"]
    list_filter = ["status", "type", "tenant"]


@admin.register(ProofOfDelivery)
class ProofOfDeliveryAdmin(ModelAdmin):
    list_display = ["delivery_task", "type", "recipient_name", "created_at"]
    list_filter = ["type", "tenant"]
