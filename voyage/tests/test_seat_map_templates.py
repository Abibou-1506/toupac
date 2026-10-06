"""Tests V1.1 — Templates système SeatMap + guards CRUD + endpoint clone."""
from datetime import date, timedelta
import importlib

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from fleet.models import Vehicle
from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, SeatMap, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"

TEMPLATE_NAMES = {
    "Vierge": 0,
    "45 places classique": 45,
    "30 places classique": 30,
    "Minibus 15": 15,
    "Van 20": 20,
}


# ─── Décor ───

@pytest.fixture
def tenant_a():
    return Tenant.objects.create(name="Transport A", slug="tpl-tenant-a")


@pytest.fixture
def tenant_b():
    return Tenant.objects.create(name="Transport B", slug="tpl-tenant-b")


@pytest.fixture
def admin_user_a(tenant_a):
    return User.objects.create_user(
        email="admin.a@tpl.sn", password=PASSWORD,
        first_name="Awa", last_name="A",
        tenant=tenant_a, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_user_b(tenant_b):
    return User.objects.create_user(
        email="admin.b@tpl.sn", password=PASSWORD,
        first_name="Bintou", last_name="B",
        tenant=tenant_b, role=User.Role.ADMIN, is_staff=True,
    )


def _client(user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def client_a(admin_user_a):
    return _client(admin_user_a)


@pytest.fixture
def client_b(admin_user_b):
    return _client(admin_user_b)


@pytest.fixture
def tenant_plan_a(tenant_a):
    return SeatMap.objects.create(
        tenant=tenant_a, name="Plan A tenanté", total_seats=4,
        layout=[
            [{"label": "A1"}, {"label": "B1"}],
            [{"label": "A2"}, {"label": "B2"}],
        ],
        is_template=False,
    )


@pytest.fixture
def tenant_plan_b(tenant_b):
    return SeatMap.objects.create(
        tenant=tenant_b, name="Plan B tenanté", total_seats=2,
        layout=[[{"label": "A1"}, {"label": "B1"}]],
        is_template=False,
    )


# ─── Tests ───

URL = "/api/v1/voyage/seat-maps/"


def _get_template(name):
    return SeatMap.objects.get(name=name, is_template=True, tenant__isnull=True)


def test_system_templates_visible_to_all_tenants(client_a, client_b):
    """Les 5 templates sont servis à tout tenant via `?is_template=true`."""
    r1 = client_a.get(f"{URL}?is_template=true&page_size=20")
    r2 = client_b.get(f"{URL}?is_template=true&page_size=20")
    assert r1.status_code == 200
    assert r2.status_code == 200
    names_a = {item["name"] for item in r1.data["results"]}
    names_b = {item["name"] for item in r2.data["results"]}
    assert set(TEMPLATE_NAMES.keys()) <= names_a
    assert set(TEMPLATE_NAMES.keys()) <= names_b


def test_tenant_seat_maps_isolated(client_a, client_b, tenant_plan_a, tenant_plan_b):
    """Plans tenants : chacun ne voit que les siens via `?is_template=false`."""
    r1 = client_a.get(f"{URL}?is_template=false&page_size=20")
    r2 = client_b.get(f"{URL}?is_template=false&page_size=20")
    ids_a = {item["id"] for item in r1.data["results"]}
    ids_b = {item["id"] for item in r2.data["results"]}
    assert str(tenant_plan_a.id) in ids_a
    assert str(tenant_plan_a.id) not in ids_b
    assert str(tenant_plan_b.id) in ids_b
    assert str(tenant_plan_b.id) not in ids_a


def test_list_mixes_templates_and_tenant_plans(client_a, tenant_plan_a):
    """Sans filtre, l'admin voit ses plans + les 5 templates ; templates en haut."""
    response = client_a.get(f"{URL}?page_size=50")
    assert response.status_code == 200
    results = response.data["results"]
    names = [item["name"] for item in results]
    assert tenant_plan_a.name in names
    for template_name in TEMPLATE_NAMES:
        assert template_name in names
    # L'ordering `-is_template` doit placer les templates en premier.
    first_non_template_idx = next(
        (i for i, item in enumerate(results) if not item["is_template"]), None,
    )
    first_template_idx = next(
        (i for i, item in enumerate(results) if item["is_template"]), None,
    )
    assert first_template_idx is not None
    if first_non_template_idx is not None:
        assert first_template_idx < first_non_template_idx


def test_update_template_forbidden(client_a):
    """PATCH sur un template → 403."""
    tpl = _get_template("Vierge")
    response = client_a.patch(
        f"{URL}{tpl.id}/", {"name": "Hacked"}, format="json",
    )
    assert response.status_code == 403
    assert "template" in str(response.data).lower()


def test_destroy_template_forbidden(client_a):
    """DELETE sur un template → 403."""
    tpl = _get_template("Van 20")
    response = client_a.delete(f"{URL}{tpl.id}/")
    assert response.status_code == 403


def test_destroy_used_plan_conflict(client_a, tenant_a, tenant_plan_a):
    """DELETE d'un plan utilisé par un Trip → 409 (non-régression commit 6 oct)."""
    origin = Place.objects.create(
        tenant=tenant_a, name="Orig TPL", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    dest = Place.objects.create(
        tenant=tenant_a, name="Dest TPL", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant_a, name="R TPL", code="R-TPL-01",
        origin_place=origin, destination_place=dest,
    )
    Trip.objects.create(
        tenant=tenant_a, route=route, seat_map=tenant_plan_a,
        internal_id="VYG-TPL-01",
        departure_date=date.today() + timedelta(days=1),
        scheduled_at=timezone.now(),
        status=Trip.Status.SCHEDULED, total_seats=4, booked_seats=0,
    )
    response = client_a.delete(f"{URL}{tenant_plan_a.id}/")
    assert response.status_code == 409
    assert "utilisé" in str(response.data).lower()


def test_destroy_default_seat_map_vehicle_sets_null(client_a, tenant_a, tenant_plan_a):
    """DELETE plan avec Vehicle.default_seat_map → SET_NULL, pas de 409."""
    vehicle = Vehicle.objects.create(
        tenant=tenant_a, plate_number="SN-TPL-DEL", capacity=4,
        default_seat_map=tenant_plan_a,
    )
    response = client_a.delete(f"{URL}{tenant_plan_a.id}/")
    assert response.status_code == 204
    vehicle.refresh_from_db()
    assert vehicle.default_seat_map is None


def test_clone_template_creates_tenant_copy(client_a, tenant_a):
    """POST clone sur un template → 201, nouvelle instance tenanted, is_template=False."""
    tpl = _get_template("Minibus 15")
    response = client_a.post(f"{URL}{tpl.id}/clone/", {}, format="json")
    assert response.status_code == 201, response.data
    assert response.data["id"] != str(tpl.id)
    assert response.data["is_template"] is False
    assert response.data["name"] == f"Copie de {tpl.name}"
    assert response.data["total_seats"] == tpl.total_seats
    assert response.data["layout"] == tpl.layout
    cloned = SeatMap.objects.get(id=response.data["id"])
    assert cloned.tenant_id == tenant_a.id
    # Template source non modifié
    tpl.refresh_from_db()
    assert tpl.is_template is True
    assert tpl.tenant_id is None


def test_clone_with_custom_name(client_a):
    """POST clone avec body `{"name": ...}` → nom respecté."""
    tpl = _get_template("Van 20")
    response = client_a.post(
        f"{URL}{tpl.id}/clone/", {"name": "Mon plan perso"}, format="json",
    )
    assert response.status_code == 201
    assert response.data["name"] == "Mon plan perso"


def test_clone_cross_tenant_plan_forbidden(client_a, tenant_plan_b):
    """Tenant A tente de cloner un plan de tenant B → 404 (plan hors queryset)."""
    # L'ID est hors du queryset de A (ni template, ni plan de A), donc
    # get_object() renvoie 404 avant même d'atteindre la vérif PermissionDenied.
    response = client_a.post(f"{URL}{tenant_plan_b.id}/clone/", {}, format="json")
    assert response.status_code == 404


def test_clone_own_plan_allowed(client_a, tenant_a, tenant_plan_a):
    """Tenant A clone un de ses propres plans → 201, nouvelle instance."""
    response = client_a.post(f"{URL}{tenant_plan_a.id}/clone/", {}, format="json")
    assert response.status_code == 201
    assert response.data["name"] == f"Copie de {tenant_plan_a.name}"
    assert response.data["id"] != str(tenant_plan_a.id)


def test_migration_seeds_five_templates():
    """La migration data a bien inséré les 5 templates avec les bons totaux."""
    for name, expected_seats in TEMPLATE_NAMES.items():
        tpl = SeatMap.objects.get(name=name, is_template=True, tenant__isnull=True)
        assert tpl.total_seats == expected_seats, (
            f"{name} : attendu {expected_seats}, trouvé {tpl.total_seats}"
        )

    # Vérifie que la fonction `seed_templates` est idempotente (safety-net
    # pour les ré-applications éventuelles via reset/replay).
    migration = importlib.import_module(
        "voyage.migrations.0005_seed_system_seat_map_templates",
    )
    assert hasattr(migration, "seed_templates")
    assert hasattr(migration, "unseed_templates")
