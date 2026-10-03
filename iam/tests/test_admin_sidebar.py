"""Tests de la sidebar enrichie (Ticket 3, C7 + 3B restructure + fix post-3B).

Vérifie :
- show_search / command_search sont bien activés (markers HTML stables) ;
- les 4 sections top-level (Supervision/Administration/Opérations/Système)
  sont effectivement rendues dans le DOM — garde-fou contre les rejets
  silencieux d'Unfold sur une structure invalide ;
- les callbacks sidebar_badges retournent la bonne valeur selon le contexte ;
- scoping tenant correct (admin de compagnie vs superadmin).
"""
import pytest
from django.test import Client, RequestFactory
from django.urls import reverse

from colis.models import Order
from iam.sidebar_badges import (
    incidents_open_count,
    orders_in_progress_count,
    trips_today_count,
)
from iam.tests.customer_factories import make_order, make_trip
from voyage.models import Incident

# ─── Non-régression : les 11 groupes de la sidebar sont rendus ───

@pytest.mark.django_db
@pytest.mark.parametrize("group_title", [
    "Tableau de bord",
    "Organisation",
    # Les `&` sont escapés en `&amp;` dans le DOM : on asserte sur une
    # moitié du titre pour éviter de dépendre de l'encodage de l'esperluette.
    "API",
    "Flotte",
    "Géographie",
    "Voyages",
    # Même raison : « Colis & Livraison » → cible la 2e moitié qui est stable.
    "Livraison",
    "Facturation",
    "Tracking GPS",
    "Notifications",
    "Workflow",
])
def test_sidebar_groups_all_rendered(superadmin, group_title):
    """Garde-fou : chaque groupe sidebar est présent dans le HTML du superadmin.

    Détecte toute régression type Ticket 3B où un pattern sidebar incompatible
    avec la version de django-unfold installée droppe silencieusement un ou
    plusieurs groupes au niveau _get_navigation_items. Un simple substring sur
    le titre de groupe est suffisant — Unfold rend les titres de groupe tels
    quels dans le DOM, à l'exception des caractères HTML (`&` → `&amp;`).
    """
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    content = response.content.decode()
    assert group_title in content, (
        f"Groupe sidebar « {group_title} » absent du HTML — "
        f"vérifier UNFOLD['SIDEBAR']['navigation']."
    )


@pytest.fixture
def rf():
    return RequestFactory()


# ─── show_search / command_search ───

@pytest.mark.django_db
def test_sidebar_search_markers_present(superadmin):
    """La search bar sidebar et le command palette sont référencés dans /admin/."""
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:index"))
    content = response.content.decode().lower()
    # Un des deux markers d'Unfold pour la search sidebar/command.
    assert "command" in content or "search" in content


# ─── trips_today_count ───

@pytest.mark.django_db
def test_trips_today_count_returns_none_when_zero(rf, superadmin):
    """0 trips aujourd'hui → None (pas de badge)."""
    request = rf.get("/admin/")
    request.user = superadmin
    assert trips_today_count(request) is None


@pytest.mark.django_db
def test_trips_today_count_returns_count_for_superadmin(rf, superadmin, tenant_a):
    """Superadmin : count global, tous tenants confondus."""
    make_trip(tenant_a)  # default departure_date = today + 7
    # Pour avoir un trip "aujourd'hui", on surcharge la date.
    from django.utils import timezone
    make_trip(tenant_a, departure_date=timezone.localdate())
    request = rf.get("/admin/")
    request.user = superadmin
    assert trips_today_count(request) == 1


@pytest.mark.django_db
def test_trips_today_count_scoped_for_tenant_admin(rf, user_admin_a, tenant_a, tenant_b):
    """Admin tenant_a : voit uniquement les trips de A."""
    from django.utils import timezone
    today = timezone.localdate()
    make_trip(tenant_a, departure_date=today)
    make_trip(tenant_b, departure_date=today)
    request = rf.get("/admin/")
    request.user = user_admin_a
    assert trips_today_count(request) == 1


# ─── incidents_open_count ───

@pytest.mark.django_db
def test_incidents_open_count_excludes_resolved(rf, superadmin, user_admin_a, tenant_a):
    """RESOLVED exclu, les autres statuts comptent."""
    trip = make_trip(tenant_a)
    Incident.objects.create(
        tenant=tenant_a, trip=trip, reporter=user_admin_a,
        type=Incident.Type.OTHER, severity=Incident.Severity.LOW,
        title="open", status=Incident.Status.REPORTED,
    )
    Incident.objects.create(
        tenant=tenant_a, trip=trip, reporter=user_admin_a,
        type=Incident.Type.OTHER, severity=Incident.Severity.LOW,
        title="closed", status=Incident.Status.RESOLVED,
    )
    request = rf.get("/admin/")
    request.user = superadmin
    assert incidents_open_count(request) == 1


# ─── orders_in_progress_count ───

@pytest.mark.django_db
def test_orders_in_progress_count_only_active_statuses(rf, superadmin, tenant_a):
    """Seuls les 4 statuts actifs comptent."""
    make_order(tenant_a, status=Order.Status.CONFIRMED)
    make_order(tenant_a, status=Order.Status.DRAFT)       # exclu
    make_order(tenant_a, status=Order.Status.DELIVERED)   # exclu
    request = rf.get("/admin/")
    request.user = superadmin
    assert orders_in_progress_count(request) == 1


# ─── Staff orphelin (anormal) ───

@pytest.mark.django_db
def test_counts_none_for_anonymous_user(rf):
    """Un request sans user authentifié → None (sécurité par défaut)."""
    from django.contrib.auth.models import AnonymousUser
    request = rf.get("/admin/")
    request.user = AnonymousUser()
    assert trips_today_count(request) is None
    assert incidents_open_count(request) is None
    assert orders_in_progress_count(request) is None
