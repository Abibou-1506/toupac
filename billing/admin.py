"""TOUPAC Billing — Configuration Django Admin + unfold."""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Invoice, InvoiceLine, Payment, PriceList, PriceRule


class PriceRuleInline(TabularInline):
    model = PriceRule
    extra = 0


class InvoiceLineInline(TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(PriceList)
class PriceListAdmin(ModelAdmin):
    list_display = ["name", "type", "currency", "is_active", "tenant"]
    list_filter = ["type", "is_active", "tenant"]
    inlines = [PriceRuleInline]


@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
    list_display = ["invoice_number", "customer_name", "total_xof", "status", "issue_date"]
    list_filter = ["status", "tenant"]
    search_fields = ["invoice_number", "customer_name"]
    inlines = [InvoiceLineInline]


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ["provider", "amount_xof", "status", "provider_tx_id", "reservation", "order", "initiated_at"]
    list_filter = ["provider", "status", "tenant"]
    search_fields = ["provider_tx_id"]
