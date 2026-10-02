"""
TOUPAC IAM — Tests du dashboard admin (Ticket 2 T2).

Vérifie :
- `compute_stats` isolé par tenant pour un admin de compagnie ;
- `compute_stats` agrégé pour superadmin (tenant=None) ;
- edge cases : zéro voyage, zéro paiement, paiement hors fenêtre, mauvais
  statut, DRAFT/terminaux exclus pour Order, seul RESOLVED exclu pour
  Incident ;
- `/admin/` répond 200 et contient les 4 cards attendues ;
- nombre de queries borné à 4 pour `compute_stats` (zéro N+1).

Pattern : `Client() + force_login` pour l'intégration, appels directs à
`compute_stats` pour l'unitaire (DECISIONS.md « compter les queries d'un
service »).

Factories réutilisées : `iam/tests/customer_factories.py` expose déjà
`make_trip`, `make_order`, `make_payment` qui absorbent les champs
obligatoires (route, places, numéro interne, etc.). On ajoute ici un
seul helper local pour `Incident` — reporter + trip + type sont requis
par le modèle, aucune fabrique partagée ne les monte aujourd'hui.
"""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from billing.models import Payment
from colis.models import Order
from iam.dashboard import compute_stats
from iam.models import User
from iam.tests.customer_factories import make_order, make_payment, make_trip
from voyage.models import Incident

# ─── Helpers locaux ───

def make_incident(tenant, trip, reporter, status=Incident.Status.REPORTED):
    """Un incident minimal. reporter + trip + type sont imposés par le modèle."""
    return Incident.objects.create(
        tenant=tenant, trip=trip, reporter=reporter,
        type=Incident.Type.OTHER, severity=Incident.Severity.LOW,
        title=f"Incident {status}",
        status=status,
    )


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def reporter_a(tenant_a):
    """Un user rattaché à tenant_a pour reporter des incidents."""
    return User.objects.create_user(
        email="reporter.a@toupac.sn", password="TestPass#2026",
        first_name="Rep", last_name="Orter",
        tenant=tenant_a, role=User.Role.CONTROLLER,
    )


# ─── compute_stats — isolation tenant ───

@pytest.mark.django_db
def test_compute_stats_counts_only_tenant_trips_today(tenant_a, tenant_b, today):
    """Un trip de B aujourd'hui n'apparaît pas dans les stats de A."""
    make_trip(tenant_a, departure_date=today)
    make_trip(tenant_b, departure_date=today)

    assert compute_stats(tenant=tenant_a)["trips_today"] == 1
    assert compute_stats(tenant=tenant_b)["trips_today"] == 1


@pytest.mark.django_db
def test_compute_stats_global_includes_all_tenants(tenant_a, tenant_b, today):
    """Avec tenant=None (superadmin), on voit les trips de A ET de B."""
    make_trip(tenant_a, departure_date=today)
    make_trip(tenant_b, departure_date=today)

    assert compute_stats(tenant=None)["trips_today"] == 2


@pytest.mark.django_db
def test_trips_today_ignores_other_days(tenant_a, today):
    """Un trip la veille ou le lendemain n'est pas compté."""
    make_trip(tenant_a, departure_date=today - timedelta(days=1))
    make_trip(tenant_a, departure_date=today + timedelta(days=1))

    assert compute_stats(tenant=tenant_a)["trips_today"] == 0


# ─── compute_stats — logique métier CA du mois ───

@pytest.mark.django_db
def test_revenue_month_includes_success_payments_in_window(tenant_a):
    """Un Payment success dans le mois courant est compté dans le CA."""
    make_payment(
        tenant_a, amount_xof=50000,
        status=Payment.Status.SUCCESS, completed_at=timezone.now(),
    )
    assert compute_stats(tenant=tenant_a)["revenue_month_xof"] == 50000


@pytest.mark.django_db
def test_revenue_month_excludes_payments_before_window(tenant_a):
    """Un Payment success daté du mois dernier n'est pas compté."""
    now = timezone.localtime()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_last_day = first_of_month - timedelta(seconds=1)

    make_payment(
        tenant_a, amount_xof=99999,
        status=Payment.Status.SUCCESS, completed_at=last_month_last_day,
    )
    assert compute_stats(tenant=tenant_a)["revenue_month_xof"] == 0


@pytest.mark.django_db
def test_revenue_month_excludes_non_success_payments(tenant_a):
    """Un Payment pending ou failed dans le mois n'est pas compté."""
    now = timezone.now()
    make_payment(
        tenant_a, amount_xof=10000,
        status=Payment.Status.PENDING, completed_at=now,
    )
    make_payment(
        tenant_a, amount_xof=20000,
        status=Payment.Status.FAILED, completed_at=now,
    )
    assert compute_stats(tenant=tenant_a)["revenue_month_xof"] == 0


@pytest.mark.django_db
def test_revenue_month_sums_multiple_payments(tenant_a):
    """Deux acomptes du mois sont additionnés — pas de double comptage, pas d'oubli."""
    now = timezone.now()
    make_payment(
        tenant_a, amount_xof=15000,
        status=Payment.Status.SUCCESS, completed_at=now,
    )
    make_payment(
        tenant_a, amount_xof=25000,
        status=Payment.Status.SUCCESS, completed_at=now,
    )
    assert compute_stats(tenant=tenant_a)["revenue_month_xof"] == 40000


# ─── compute_stats — Order.in_progress ───

@pytest.mark.django_db
def test_orders_in_progress_excludes_draft_and_terminal(tenant_a):
    """DRAFT exclu, DELIVERED/FAILED/CANCELLED aussi, les 4 intermédiaires comptés."""
    for status in [
        Order.Status.DRAFT,
        Order.Status.CONFIRMED,
        Order.Status.DISPATCHED,
        Order.Status.PICKED_UP,
        Order.Status.IN_TRANSIT,
        Order.Status.DELIVERED,
        Order.Status.FAILED,
        Order.Status.CANCELLED,
    ]:
        make_order(tenant_a, status=status)

    # 4 statuts actifs retenus : CONFIRMED, DISPATCHED, PICKED_UP, IN_TRANSIT.
    assert compute_stats(tenant=tenant_a)["orders_in_progress"] == 4


# ─── compute_stats — Incident.open ───

@pytest.mark.django_db
def test_incidents_open_excludes_resolved_only(tenant_a, reporter_a, today):
    """REPORTED, NOTIFIED, IN_PROGRESS comptés — seul RESOLVED exclu."""
    trip = make_trip(tenant_a, departure_date=today)
    for status in [
        Incident.Status.REPORTED,
        Incident.Status.NOTIFIED,
        Incident.Status.IN_PROGRESS,
        Incident.Status.RESOLVED,
    ]:
        make_incident(tenant_a, trip, reporter_a, status=status)

    assert compute_stats(tenant=tenant_a)["incidents_open"] == 3


# ─── compute_stats — edge cases ───

@pytest.mark.django_db
def test_compute_stats_returns_zero_for_empty_tenant(tenant_trial):
    """Un tenant sans données retourne des zéros propres, pas None."""
    assert compute_stats(tenant=tenant_trial) == {
        "trips_today": 0,
        "orders_in_progress": 0,
        "incidents_open": 0,
        "revenue_month_xof": 0,
    }


# ─── Performance ───

@pytest.mark.django_db
def test_compute_stats_runs_in_at_most_4_queries(django_assert_num_queries, tenant_a):
    """4 stats = 4 queries max. Pas de N+1 toléré."""
    with django_assert_num_queries(4):
        compute_stats(tenant=tenant_a)


# ─── Intégration /admin/ ───

@pytest.mark.django_db
def test_admin_index_shows_cards_for_tenant_admin(user_admin_a):
    client = Client()
    client.force_login(user_admin_a)
    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    content = response.content.decode()
    # Assertions sur les titres des 4 cards. On teste sur « Voyages aujourd »
    # (sans l'apostrophe) parce que Django échappe `'` en `&#x27;` dans la
    # sortie HTML — faire assert sur « Voyages aujourd'hui » échouerait, le
    # markup réel étant « Voyages aujourd&#x27;hui ». Pas d'assertion sur
    # les valeurs (dépendent des fixtures) ni sur le markup CSS interne.
    assert "Voyages aujourd" in content
    assert "Commandes en cours" in content
    assert "Incidents ouverts" in content
    assert "CA du mois" in content


@pytest.mark.django_db
def test_admin_index_shows_cards_for_superadmin(superadmin):
    """Le superadmin voit le même dashboard, données globales."""
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    # Idem test précédent : « Voyages aujourd » sans l'apostrophe pour
    # survivre à l'auto-escape HTML de Django.
    assert "Voyages aujourd" in response.content.decode()


@pytest.mark.django_db
def test_admin_index_still_shows_app_list(user_admin_a):
    """Le dashboard ajoute, ne remplace pas : la liste des apps reste visible."""
    client = Client()
    client.force_login(user_admin_a)
    response = client.get(reverse("admin:index"))
    content = response.content.decode()

    # Au moins un lien d'app Django Admin natif présent par défaut sur
    # /admin/. On tolère plusieurs cibles car has_module_permission peut
    # masquer certaines apps selon les permissions du user.
    assert "/admin/voyage/" in content or "/admin/colis/" in content
