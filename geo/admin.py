"""TOUPAC Geo — Configuration Django Admin + unfold.

Le widget carte OpenLayers de GeoDjango ne s'affiche pas correctement dans
l'admin unfold (conteneur CSS à hauteur 0). On remplace donc les widgets
géométriques par de simples champs texte WKT — Django/GEOS parsent le WKT
saisi indépendamment du widget utilisé pour l'afficher.
"""
from django import forms
from django.contrib import admin
from django.contrib.gis import forms as gis_forms
from unfold.admin import ModelAdmin

from .models import Place, Zone


class PlaceAdminForm(forms.ModelForm):
    class Meta:
        model = Place
        fields = "__all__"
        widgets = {
            "location": forms.TextInput(attrs={
                "placeholder": "POINT(longitude latitude) ex: POINT(-17.4441 14.6937)",
                "style": "width: 100%;",
            }),
        }


class ZoneAdminForm(forms.ModelForm):
    boundary = gis_forms.PolygonField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "style": "width: 100%; font-family: monospace;",
            "placeholder": "POLYGON((lng1 lat1, lng2 lat2, lng3 lat3, lng1 lat1))",
        }),
        help_text=(
            "Saisie WKT peu pratique à la main. Utilisez l'API "
            "/api/v1/geo/zones/ pour créer des zones avec du GeoJSON."
        ),
    )

    class Meta:
        model = Zone
        fields = "__all__"


@admin.register(Place)
class PlaceAdmin(ModelAdmin):
    form = PlaceAdminForm
    list_display = ["name", "city", "country_code", "type", "latitude", "longitude", "tenant"]
    list_filter = ["type", "country_code", "tenant"]
    search_fields = ["name", "city", "address"]

    def latitude(self, obj):
        if obj.location:
            return obj.location.y
        return None
    latitude.short_description = "Latitude"

    def longitude(self, obj):
        if obj.location:
            return obj.location.x
        return None
    longitude.short_description = "Longitude"


@admin.register(Zone)
class ZoneAdmin(ModelAdmin):
    form = ZoneAdminForm
    list_display = ["name", "type", "is_active", "tenant"]
    list_filter = ["type", "is_active", "tenant"]
