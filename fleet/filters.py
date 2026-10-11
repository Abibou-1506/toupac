"""TOUPAC Fleet — FilterSets django-filter.

Expose les filtres riches sur ``Driver`` (dette V1.1 Vague 4) :
- ``license_classes`` : filtre CSV (``?license_classes=B,D``) sur l'ArrayField
  via ``__overlap`` (au moins une catégorie demandée présente).
- ``is_assigned`` : filtre booléen (``?is_assigned=true/false``) basé sur la
  reverse FK ``Vehicle.assigned_driver`` via ``Exists`` pour éviter les
  doublons de jointure.
"""
from django.db.models import Exists, OuterRef
from django_filters import rest_framework as filters

from .models import Driver, Vehicle


class DriverFilterSet(filters.FilterSet):
    """Filtres de la page liste des chauffeurs (backoffice DS)."""

    license_classes = filters.CharFilter(method="filter_license_classes")
    is_assigned = filters.CharFilter(method="filter_is_assigned")

    class Meta:
        model = Driver
        fields = ["status"]

    def filter_license_classes(self, queryset, name, value):
        """Accepte CSV (``?license_classes=B,D``). Retourne les chauffeurs
        possédant au moins une des catégories demandées."""
        if value is None:
            return queryset
        classes = [c.strip() for c in value.split(",") if c.strip()]
        if not classes:
            return queryset
        return queryset.filter(license_classes__overlap=classes)

    def filter_is_assigned(self, queryset, name, value):
        """``true`` → chauffeurs ayant au moins un véhicule affecté.
        ``false`` → chauffeurs sans affectation."""
        if value is None or value == "":
            return queryset
        want_assigned = value.lower() in ("true", "1", "yes")
        return queryset.annotate(
            _is_assigned=Exists(
                Vehicle.objects.filter(assigned_driver=OuterRef("pk")),
            ),
        ).filter(_is_assigned=want_assigned)
