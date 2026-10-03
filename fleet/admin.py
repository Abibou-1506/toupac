"""TOUPAC Fleet — Configuration Django Admin + unfold.

Widgets géométriques remplacés par de simples champs texte WKT — cf.
geo/admin.py pour le contexte (carte OpenLayers cassée dans l'admin unfold).

Enrichi au Ticket 3 : fieldsets français groupés sur Vehicle/Driver (2 des 8
admins « lourds »), list_select_related sur FK du list_display, filtres
Unfold overlay, readonly_fields sur les champs auto-remplis.
"""
from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)

from core.admin import TenantAdminMixin

from .models import Driver, Fleet, Vehicle, VehicleDocument, VehicleType


class VehicleDocumentInline(TabularInline):
    model = VehicleDocument
    extra = 0


class VehicleAdminForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = "__all__"
        widgets = {
            "location": forms.TextInput(attrs={
                "placeholder": "POINT(longitude latitude) ex: POINT(-17.4441 14.6937)",
                "style": "width: 100%;",
            }),
        }


class DriverAdminForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = "__all__"
        widgets = {
            "last_known_location": forms.TextInput(attrs={
                "placeholder": "POINT(longitude latitude) ex: POINT(-17.4441 14.6937)",
                "style": "width: 100%;",
            }),
        }


@admin.register(VehicleType)
class VehicleTypeAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "default_capacity", "fuel_type", "tenant"]
    list_select_related = ["tenant"]
    list_filter = [("tenant", RelatedDropdownFilter)]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Vehicle)
class VehicleAdmin(TenantAdminMixin, ModelAdmin):
    form = VehicleAdminForm
    list_display = ["plate_number", "make", "model_name", "capacity", "status", "vehicle_type", "tenant"]
    list_select_related = ["vehicle_type", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("vehicle_type", RelatedDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["plate_number", "make", "vin"]
    inlines = [VehicleDocumentInline]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("plate_number", "vehicle_type", "status")}),
        ("Caractéristiques", {"fields": ("make", "model_name", "year", "vin", "capacity")}),
        ("Localisation", {"fields": ("location",)}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Driver)
class DriverAdmin(TenantAdminMixin, ModelAdmin):
    form = DriverAdminForm
    list_display = ["user", "license_number", "license_class", "status", "score", "tenant"]
    list_select_related = ["user", "tenant"]
    list_filter = [("status", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    search_fields = ["user__first_name", "user__last_name", "license_number"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("user", "status", "score")}),
        ("Licence", {"fields": ("license_number", "license_class", "license_expiry")}),
        ("Localisation", {"fields": ("last_known_location",)}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Fleet)
class FleetAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "zone", "manager", "tenant"]
    list_select_related = ["manager", "tenant"]
    list_filter = [("tenant", RelatedDropdownFilter)]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]
