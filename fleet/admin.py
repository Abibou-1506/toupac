"""TOUPAC Fleet — Configuration Django Admin + unfold.

Widgets géométriques remplacés par de simples champs texte WKT — cf.
geo/admin.py pour le contexte (carte OpenLayers cassée dans l'admin unfold).
"""
from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import VehicleType, Vehicle, Driver, VehicleDocument, Fleet, FleetVehicle

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
class VehicleTypeAdmin(ModelAdmin):
    list_display = ["name", "default_capacity", "fuel_type", "tenant"]
    list_filter = ["tenant"]

@admin.register(Vehicle)
class VehicleAdmin(ModelAdmin):
    form = VehicleAdminForm
    list_display = ["plate_number", "make", "model_name", "capacity", "status", "vehicle_type", "tenant"]
    list_filter = ["status", "vehicle_type", "tenant"]
    search_fields = ["plate_number", "make", "vin"]
    inlines = [VehicleDocumentInline]

@admin.register(Driver)
class DriverAdmin(ModelAdmin):
    form = DriverAdminForm
    list_display = ["user", "license_number", "license_class", "status", "score", "tenant"]
    list_filter = ["status", "tenant"]
    search_fields = ["user__first_name", "user__last_name", "license_number"]

@admin.register(Fleet)
class FleetAdmin(ModelAdmin):
    list_display = ["name", "zone", "manager", "tenant"]
    list_filter = ["tenant"]
