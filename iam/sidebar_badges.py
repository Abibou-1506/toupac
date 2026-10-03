"""Callbacks qui calculent les badges numériques affichés dans la sidebar admin.

Appelés à chaque rendu de l'admin (une invocation par item par page admin).
Perf : chaque callback fait 1 count SQL max, zéro N+1, sinon toute la
sidebar ralentit.

Les callbacks reçoivent `request` et retournent un entier à afficher dans
le badge, ou `None` pour masquer le badge (c'est le choix préféré quand
count = 0 — un « 0 » permanent est du bruit visuel).

Scoping cohérent avec le dashboard du Ticket 2 et avec TenantAdminMixin :
- superadmin → stats globales (toutes compagnies).
- admin de compagnie → stats de son tenant.
- staff orphelin → None (pas de badge).
"""
from core.admin import TenantAdminMixin


def _scope_queryset(request, qs):
    """Filtre un queryset selon le profil du user (superadmin vs admin tenant).

    Retourne None si le user est un staff orphelin — l'appelant doit alors
    retourner None pour masquer le badge.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    if TenantAdminMixin._is_superadmin(user):
        return qs
    tenant = getattr(user, "tenant", None)
    if tenant is None:
        return None
    return qs.filter(tenant=tenant)


def incidents_open_count(request):
    """Nombre d'incidents non résolus visibles pour l'utilisateur."""
    from voyage.models import Incident

    qs = _scope_queryset(
        request, Incident.objects.exclude(status=Incident.Status.RESOLVED),
    )
    if qs is None:
        return None
    count = qs.count()
    return count if count > 0 else None


def orders_in_progress_count(request):
    """Nombre de commandes dans un statut actif (cf. Ticket 2, dashboard)."""
    from colis.models import Order

    qs = _scope_queryset(
        request,
        Order.objects.filter(status__in=[
            Order.Status.CONFIRMED,
            Order.Status.DISPATCHED,
            Order.Status.PICKED_UP,
            Order.Status.IN_TRANSIT,
        ]),
    )
    if qs is None:
        return None
    count = qs.count()
    return count if count > 0 else None


def trips_today_count(request):
    """Nombre de voyages dont la date de départ est aujourd'hui."""
    from django.utils import timezone

    from voyage.models import Trip

    qs = _scope_queryset(request, Trip.objects.filter(departure_date=timezone.localdate()))
    if qs is None:
        return None
    count = qs.count()
    return count if count > 0 else None
