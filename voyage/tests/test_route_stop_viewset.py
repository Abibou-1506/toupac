"""Tests du nouveau RouteStopViewSet (Prompt 16 Phase 2A Bloc 1).

CRUD complet + isolation tenant + validators + action /reorder/ + 409 PROTECT
quand des TripStop pointent sur un RouteStop (signal matérialisation Prompt 8).
"""
from datetime import UTC, datetime

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, RouteStop, Trip, TripStop

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"
BASE_URL = "/api/v1/voyage/route-stops/"


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport RouteStop", slug="rs-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.rs@toupac.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def places(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar RS", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    intermediate = Place.objects.create(
        tenant=tenant, name="Kaolack RS", type=Place.PlaceType.STATION,
        location=Point(-16.07, 14.17, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès RS", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    return {"origin": origin, "intermediate": intermediate, "destination": destination}


@pytest.fixture
def route(tenant, places):
    return Route.objects.create(
        tenant=tenant, name="DKR-THS RS", code="R-RS-01",
        origin_place=places["origin"], destination_place=places["destination"],
    )


@pytest.fixture
def stops(tenant, route, places):
    """3 stops ordonnés 0/1/2 avec offsets cohérents."""
    s0 = RouteStop.objects.create(
        tenant=tenant, route=route, place=places["origin"], stop_order=0,
        arrival_offset_minutes=0, departure_offset_minutes=0,
    )
    s1 = RouteStop.objects.create(
        tenant=tenant, route=route, place=places["intermediate"], stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=630,
    )
    s2 = RouteStop.objects.create(
        tenant=tenant, route=route, place=places["destination"], stop_order=2,
        arrival_offset_minutes=1200, departure_offset_minutes=1200,
    )
    return [s0, s1, s2]


# ─── Fixtures tenant_b pour isolation ─────────────────────────────────


@pytest.fixture
def tenant_b():
    return Tenant.objects.create(name="Transport B", slug="rs-tenant-b")


@pytest.fixture
def admin_b(tenant_b):
    return User.objects.create_user(
        email="admin.b@toupac.sn", password=PASSWORD,
        first_name="Bineta", last_name="Fall",
        tenant=tenant_b, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_client_b(admin_b):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_b).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ─── CRUD ──────────────────────────────────────────────────────────────


def test_create_route_stop_201_with_full_payload(admin_client, tenant, route, places):
    payload = {
        "route": str(route.id),
        "place": str(places["intermediate"].id),
        "stop_order": 99,
        "arrival_offset_minutes": 600,
        "departure_offset_minutes": 630,
        "is_boarding": True,
        "is_alighting": True,
    }
    response = admin_client.post(BASE_URL, data=payload, format="json")
    assert response.status_code == 201, response.data
    assert response.data["stop_order"] == 99
    assert response.data["arrival_offset_minutes"] == 600
    assert response.data["departure_offset_minutes"] == 630
    assert response.data["offset_minutes"] == 630  # sync via save()
    created = RouteStop.objects.get(pk=response.data["id"])
    assert created.tenant_id == tenant.id


def test_list_route_stop_filter_by_route(admin_client, tenant, route, places, stops):
    other_route = Route.objects.create(
        tenant=tenant, name="Autre route", code="R-RS-OTHER",
        origin_place=places["origin"], destination_place=places["destination"],
    )
    RouteStop.objects.create(
        tenant=tenant, route=other_route, place=places["origin"], stop_order=0,
    )
    response = admin_client.get(BASE_URL, {"route": str(route.id)})
    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    assert len(results) == 3
    assert all(str(r["route"]) == str(route.id) for r in results)


def test_retrieve_route_stop_200(admin_client, stops):
    stop = stops[1]
    response = admin_client.get(f"{BASE_URL}{stop.id}/")
    assert response.status_code == 200
    assert response.data["id"] == str(stop.id)
    assert response.data["stop_order"] == 1


def test_patch_route_stop_updates_only_provided_fields(admin_client, stops):
    stop = stops[1]
    response = admin_client.patch(
        f"{BASE_URL}{stop.id}/",
        data={"arrival_offset_minutes": 610},
        format="json",
    )
    assert response.status_code == 200, response.data
    stop.refresh_from_db()
    assert stop.arrival_offset_minutes == 610
    assert stop.departure_offset_minutes == 630  # inchangé
    assert stop.is_boarding is True
    assert stop.is_alighting is True


def test_destroy_route_stop_204_when_no_tripstop(admin_client, stops):
    stop = stops[2]
    response = admin_client.delete(f"{BASE_URL}{stop.id}/")
    assert response.status_code == 204
    assert not RouteStop.objects.filter(pk=stop.pk).exists()


# ─── Isolation tenant ──────────────────────────────────────────────────


def test_list_scope_strict_to_tenant(admin_client_b, stops, tenant_b):
    # tenant_a a 3 stops ; tenant_b en a 0.
    response = admin_client_b.get(BASE_URL)
    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    assert results == [] or len(results) == 0


def test_retrieve_cross_tenant_returns_404(admin_client_b, stops):
    stop_from_a = stops[0]
    response = admin_client_b.get(f"{BASE_URL}{stop_from_a.id}/")
    assert response.status_code == 404


# ─── Validation ────────────────────────────────────────────────────────


def test_create_rejects_departure_before_arrival(admin_client, route, places):
    payload = {
        "route": str(route.id),
        "place": str(places["intermediate"].id),
        "stop_order": 50,
        "arrival_offset_minutes": 700,
        "departure_offset_minutes": 600,
    }
    response = admin_client.post(BASE_URL, data=payload, format="json")
    assert response.status_code == 400
    assert "departure_offset_minutes" in response.data


def test_create_rejects_both_flags_false(admin_client, route, places):
    payload = {
        "route": str(route.id),
        "place": str(places["intermediate"].id),
        "stop_order": 51,
        "arrival_offset_minutes": 100,
        "departure_offset_minutes": 100,
        "is_boarding": False,
        "is_alighting": False,
    }
    response = admin_client.post(BASE_URL, data=payload, format="json")
    assert response.status_code == 400


def test_patch_rejects_departure_before_arrival(admin_client, stops):
    # stops[1] : arrival=600 departure=630 → PATCH arrival=700 → 700 > 630 (dep) → 400
    stop = stops[1]
    response = admin_client.patch(
        f"{BASE_URL}{stop.id}/",
        data={"arrival_offset_minutes": 700},
        format="json",
    )
    assert response.status_code == 400
    assert "departure_offset_minutes" in response.data


# ─── Reorder ───────────────────────────────────────────────────────────


def test_reorder_swap_two_stops(admin_client, stops):
    # [A=0, B=1, C=2] → reorder B à new_order=0 → [B=0, A=1, C=2]
    s_a, s_b, s_c = stops
    response = admin_client.post(
        f"{BASE_URL}{s_b.id}/reorder/",
        data={"new_order": 0},
        format="json",
    )
    assert response.status_code == 200, response.data
    s_a.refresh_from_db()
    s_b.refresh_from_db()
    s_c.refresh_from_db()
    assert s_b.stop_order == 0
    assert s_a.stop_order == 1
    assert s_c.stop_order == 2


def test_reorder_shift_middle_to_last(admin_client, stops):
    # [A=0, B=1, C=2] → reorder A à 2 → [B=0, C=1, A=2]
    s_a, s_b, s_c = stops
    response = admin_client.post(
        f"{BASE_URL}{s_a.id}/reorder/",
        data={"new_order": 2},
        format="json",
    )
    assert response.status_code == 200, response.data
    s_a.refresh_from_db()
    s_b.refresh_from_db()
    s_c.refresh_from_db()
    assert s_b.stop_order == 0
    assert s_c.stop_order == 1
    assert s_a.stop_order == 2


def test_reorder_rejects_new_order_out_of_range(admin_client, stops):
    response = admin_client.post(
        f"{BASE_URL}{stops[0].id}/reorder/",
        data={"new_order": 5},
        format="json",
    )
    assert response.status_code == 400
    assert "entre 0 et 2 inclus" in response.data["detail"]


def test_reorder_rejects_negative_new_order(admin_client, stops):
    response = admin_client.post(
        f"{BASE_URL}{stops[0].id}/reorder/",
        data={"new_order": -1},
        format="json",
    )
    assert response.status_code == 400


# ─── 409 PROTECT ───────────────────────────────────────────────────────


def test_destroy_returns_409_when_tripstop_exists_with_trip_internal_id(
    admin_client, tenant, route, stops,
):
    """Un Trip actif matérialise des TripStop (signal Prompt 8).
    DELETE sur un RouteStop utilisé → 409, RouteStop et TripStop intacts.
    """
    stop = stops[1]
    trip = Trip.objects.create(
        tenant=tenant,
        route=route,
        internal_id="T-RS-20261007-01",
        departure_date=datetime(2026, 10, 10, 8, 0, tzinfo=UTC).date(),
        scheduled_at=datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
        total_seats=45,
    )
    # Signal matérialise 3 TripStop (1 par RouteStop).
    assert TripStop.objects.filter(route_stop=stop).exists()

    response = admin_client.delete(f"{BASE_URL}{stop.id}/")
    assert response.status_code == 409, response.data
    assert response.data["trip_count"] >= 1
    assert len(response.data["trip_ids"]) >= 1
    assert trip.internal_id in response.data["trip_ids"]
    # Pas d'UUID dans trip_ids : c'est bien l'internal_id humain.
    assert all(not str(tid).startswith(str(trip.id)[:8]) for tid in response.data["trip_ids"])
    # RouteStop et TripStop intacts.
    assert RouteStop.objects.filter(pk=stop.pk).exists()
    assert TripStop.objects.filter(route_stop=stop).exists()


# ─── Bonus : non-régression manifest queries ──────────────────────────


def test_manifest_queries_not_regressed_after_route_stop_crud(
    admin_client, tenant, route, stops, places,
):
    """Un reorder ne doit pas dégrader le count de requêtes du manifest
    (prefetch stops__route_stop reste efficace)."""
    trip = Trip.objects.create(
        tenant=tenant,
        route=route,
        internal_id="T-RS-MANIF-01",
        departure_date=datetime(2026, 10, 12, 8, 0, tzinfo=UTC).date(),
        scheduled_at=datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
        total_seats=45,
    )
    manifest_url = f"/api/v1/voyage/trips/{trip.id}/manifest/"

    # 1er appel pour « réchauffer » les caches lazy (connection, auth, etc.).
    admin_client.get(manifest_url)

    with CaptureQueriesContext(connection) as ctx_before:
        r1 = admin_client.get(manifest_url)
    assert r1.status_code == 200
    count_before = len(ctx_before.captured_queries)

    # Reorder : [0,1,2] → stop 2 en tête → [2→0, 0→1, 1→2]
    r_reorder = admin_client.post(
        f"{BASE_URL}{stops[2].id}/reorder/",
        data={"new_order": 0},
        format="json",
    )
    assert r_reorder.status_code == 200, r_reorder.data

    with CaptureQueriesContext(connection) as ctx_after:
        r2 = admin_client.get(manifest_url)
    assert r2.status_code == 200
    count_after = len(ctx_after.captured_queries)

    # Invariant : le reorder ne doit pas introduire de N+1 silencieux.
    assert count_after <= count_before, (
        f"Régression N+1 manifest : {count_before} → {count_after} requêtes"
    )
