"""
TOUPAC IAM — Isolation multi-tenant dans l'admin Django.

L'admin ne passe pas par les ViewSets DRF : sans TenantAdminMixin, un compte
is_staff voyait et modifiait les données de toutes les compagnies. Ces tests
tapent les URLs /admin/ avec le client de test Django (pas APIClient).

Un modèle représentatif par comportement suffit : le mixin est unique et
générique, Trip couvre le cas nominal, Place le tenant nullable, Tenant
l'absence de tenant.
"""
import pytest
from django.contrib.auth.models import Permission
from django.contrib.gis.geos import Point
from django.test import Client
from django.utils import timezone

from geo.models import Place
from iam.models import User
from voyage.models import Route, Trip

pytestmark = pytest.mark.django_db

TRIP_LIST = "/admin/voyage/trip/"
PLACE_LIST = "/admin/geo/place/"
TENANT_LIST = "/admin/iam/tenant/"


# ─── Fabriques ───

def grant_admin_permissions(user):
    """
    is_staff ne donne accès à rien : l'admin exige une permission par modèle.

    On accorde ici les mêmes droits que le groupe posé par seed_demo, pour que
    les tests mesurent le mixin et non l'absence de permissions.
    """
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label__in=["voyage", "geo", "iam"])
    )
    return user


def make_place(tenant, name, lon=-17.4441, lat=14.6937):
    return Place.objects.create(
        tenant=tenant, name=name, type=Place.PlaceType.STATION,
        location=Point(lon, lat, srid=4326),
    )


def make_route(tenant, code):
    return Route.objects.create(
        tenant=tenant, name=f"Route {code}", code=code,
        origin_place=make_place(tenant, f"Origine {code}"),
        destination_place=make_place(tenant, f"Destination {code}", -8.0029, 12.6392),
    )


def make_trip(tenant, code, internal_id):
    now = timezone.now()
    return Trip.objects.create(
        tenant=tenant, route=make_route(tenant, code), internal_id=internal_id,
        departure_date=now.date(), scheduled_at=now, total_seats=45,
    )


def admin_client(user):
    client = Client()
    client.force_login(grant_admin_permissions(user))
    return client


@pytest.fixture
def superadmin():
    return User.objects.create_user(
        email="super@toupac.sn", password="TestPass#2026", first_name="Super",
        last_name="Admin", tenant=None, role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True,
    )


@pytest.fixture
def trip_a(tenant_a):
    return make_trip(tenant_a, "AAA", "VYG-A-001")


@pytest.fixture
def trip_b(tenant_b):
    return make_trip(tenant_b, "BBB", "VYG-B-001")


def denied(response):
    """
    L'admin refuse de deux façons : 403, ou 302 vers l'index / le login.

    Sur un refus de permission d'objet, Django ne renvoie pas 403 : il
    redirige vers l'index avec un message « n'existe pas », précisément pour
    ne pas révéler que l'objet existe. Un enregistrement réussi redirige lui
    vers la changelist, d'où la distinction sur l'URL de destination.
    """
    if response.status_code == 403:
        return True
    if response.status_code != 302:
        return False
    location = response.headers.get("Location", "")
    return location == "/admin/" or "/admin/login/" in location


def trip_form_data(trip=None, **overrides):
    """
    Payload complet du formulaire admin de Trip.

    TripAdmin déclare un inline `stops` : sans ses champs de management form,
    Django rejette le POST en validation et renvoie 200 — ce qui ressemblerait
    à tort à un refus d'autorisation.
    """
    now = timezone.now()
    data = {
        "internal_id": "VYG-FORM-001",
        "route": str(trip.route_id) if trip else "",
        "departure_date": (trip.departure_date if trip else now.date()).isoformat(),
        "scheduled_at_0": (trip.scheduled_at.date() if trip else now.date()).isoformat(),
        "scheduled_at_1": "12:00:00",
        "status": Trip.Status.SCHEDULED,
        "total_seats": 45,
        "booked_seats": 0,
        "tenant": str(trip.tenant_id) if trip else "",
        "stops-TOTAL_FORMS": "0",
        "stops-INITIAL_FORMS": "0",
        "stops-MIN_NUM_FORMS": "0",
        "stops-MAX_NUM_FORMS": "1000",
    }
    data.update(overrides)
    return data


# ─── Liste ───

def test_admin_a_sees_only_own_tenant_trips_in_list(user_admin_a, trip_a, trip_b):
    response = admin_client(user_admin_a).get(TRIP_LIST)

    assert response.status_code == 200
    body = response.content.decode()
    assert trip_a.internal_id in body
    assert trip_b.internal_id not in body


# ─── Détail et édition ───

def test_admin_a_cannot_access_trip_b_detail_page(user_admin_a, trip_b):
    response = admin_client(user_admin_a).get(f"{TRIP_LIST}{trip_b.id}/change/")

    # Django renvoie 302 vers le login quand la permission d'objet est refusée.
    assert denied(response), (response.status_code, response.headers.get("Location"))


def test_admin_a_cannot_post_edit_to_trip_b(user_admin_a, trip_b):
    response = admin_client(user_admin_a).post(
        f"{TRIP_LIST}{trip_b.id}/change/",
        trip_form_data(trip_b, internal_id="PIRATE-001", status=Trip.Status.CANCELLED),
    )

    assert denied(response), response.status_code
    trip_b.refresh_from_db()
    assert trip_b.internal_id == "VYG-B-001"
    assert trip_b.status != Trip.Status.CANCELLED


def test_admin_a_can_view_and_edit_own_trip_a(user_admin_a, trip_a):
    """Contrôle positif : l'isolation ne doit pas bloquer le cas nominal."""
    client = admin_client(user_admin_a)
    assert client.get(f"{TRIP_LIST}{trip_a.id}/change/").status_code == 200

    response = client.post(
        f"{TRIP_LIST}{trip_a.id}/change/",
        trip_form_data(trip_a, internal_id="VYG-A-001-EDIT"),
    )

    assert response.status_code == 302, response.content.decode()[:1500]
    trip_a.refresh_from_db()
    assert trip_a.internal_id == "VYG-A-001-EDIT"


# ─── Création ───

def test_admin_a_creating_trip_forces_own_tenant(user_admin_a, tenant_a, tenant_b):
    route_a = make_route(tenant_a, "AAA")

    response = admin_client(user_admin_a).post(f"{TRIP_LIST}add/", trip_form_data(
        internal_id="VYG-FORGE-001", route=str(route_a.id),
        tenant=str(tenant_b.id),  # tenant forgé dans le formulaire
    ))

    assert response.status_code == 302, response.content.decode()[:2000]
    created = Trip.objects.get(internal_id="VYG-FORGE-001")
    assert created.tenant_id == tenant_a.id


def test_admin_a_dropdown_route_only_shows_own_tenant_routes(user_admin_a, tenant_a, tenant_b):
    route_a = make_route(tenant_a, "AAA")
    route_b = make_route(tenant_b, "BBB")

    response = admin_client(user_admin_a).get(f"{TRIP_LIST}add/")

    assert response.status_code == 200
    body = response.content.decode()
    assert str(route_a.id) in body
    assert str(route_b.id) not in body


# ─── Suppression ───

def test_admin_a_delete_action_blocked_on_trip_b(user_admin_a, trip_b):
    admin_client(user_admin_a).post(TRIP_LIST, {
        "action": "delete_selected", "_selected_action": [str(trip_b.id)], "post": "yes",
    })

    assert Trip.objects.filter(pk=trip_b.pk).exists()


# ─── Superadmin ───

def test_superadmin_sees_all_tenants_trips(superadmin, trip_a, trip_b):
    response = Client()
    response.force_login(superadmin)
    body = response.get(TRIP_LIST).content.decode()

    assert trip_a.internal_id in body
    assert trip_b.internal_id in body


def test_superadmin_can_edit_any_tenant_trip(superadmin, trip_b):
    client = Client()
    client.force_login(superadmin)
    assert client.get(f"{TRIP_LIST}{trip_b.id}/change/").status_code == 200

    response = client.post(
        f"{TRIP_LIST}{trip_b.id}/change/",
        trip_form_data(trip_b, internal_id="VYG-B-001-SUPER"),
    )

    assert response.status_code == 302, response.content.decode()[:2000]
    trip_b.refresh_from_db()
    assert trip_b.internal_id == "VYG-B-001-SUPER"


# ─── Modèle sans tenant : Tenant lui-même ───

def test_admin_a_cannot_see_tenant_list_at_all(user_admin_a, tenant_b):
    response = admin_client(user_admin_a).get(TENANT_LIST)

    assert denied(response), (response.status_code, response.headers.get("Location"))


# ─── Tenant nullable : places publiques ───

def test_admin_a_sees_public_places_but_cannot_edit_them(user_admin_a, tenant_a):
    public = make_place(None, "Gare publique")
    private = make_place(tenant_a, "Dépôt privé A")

    client = admin_client(user_admin_a)
    listing = client.get(PLACE_LIST)
    assert listing.status_code == 200
    body = listing.content.decode()
    assert "Gare publique" in body
    assert "Dépôt privé A" in body

    edit = client.post(f"{PLACE_LIST}{public.id}/change/", {
        "name": "Gare piratée", "city": "Dakar", "country_code": "SN",
        "type": Place.PlaceType.STATION, "location": "POINT(-17.4441 14.6937)",
    })
    assert denied(edit), edit.status_code
    public.refresh_from_db()
    assert public.name == "Gare publique"
    assert private.tenant_id == tenant_a.id
