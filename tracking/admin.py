"""TOUPAC Tracking — Configuration Django Admin + unfold.

Le widget carte OpenLayers de GeoDjango ne s'affiche pas dans l'admin unfold
(conteneur CSS à hauteur 0) — cf. geo/admin.py pour le même correctif sur
Place/Zone. Geofence.boundary est traité ici de la même façon.
"""
from django import forms
from django.contrib import admin
from django.contrib.gis import forms as gis_forms
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)

from core.admin import TenantAdminMixin

from .models import Geofence, GeofenceEvent, Position, TrackingLink


class GeofenceAdminForm(forms.ModelForm):
    boundary = gis_forms.PolygonField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "style": "width: 100%; font-family: monospace;",
            "placeholder": "POLYGON((lng1 lat1, lng2 lat2, lng3 lat3, lng1 lat1))",
        }),
        help_text=(
            "Saisie WKT peu pratique à la main. Utilisez l'API "
            "/api/v1/tracking/geofences/ pour créer des géofences avec du GeoJSON."
        ),
    )

    class Meta:
        model = Geofence
        fields = "__all__"


@admin.register(Position)
class PositionAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["vehicle", "speed_kmh", "source", "recorded_at"]
    list_select_related = ["vehicle", "tenant"]
    list_filter = [
        ("source", ChoicesDropdownFilter),
        ("vehicle", RelatedDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    date_hierarchy = "recorded_at"
    readonly_fields = [f.name for f in Position._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Geofence)
class GeofenceAdmin(TenantAdminMixin, ModelAdmin):
    form = GeofenceAdminForm
    list_display = ["name", "type", "is_active", "tenant"]
    list_select_related = ["tenant"]
    list_filter = [("type", ChoicesDropdownFilter), "is_active"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GeofenceEvent)
class GeofenceEventAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["geofence", "vehicle", "event_type", "event_at"]
    list_select_related = ["geofence", "vehicle", "tenant"]
    list_filter = [("event_type", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    date_hierarchy = "event_at"


@admin.register(TrackingLink)
class TrackingLinkAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["token", "resource_type", "resource_id", "expires_at"]
    list_select_related = ["tenant"]
    list_filter = [("resource_type", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    readonly_fields = ["created_at", "updated_at"]
