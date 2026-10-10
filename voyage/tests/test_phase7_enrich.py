"""Phase 7 — enrichissements serializers voyage pour branchement DS web.

- RouteSerializer : alias `o`/`d` city names à plat
- RouteStopSerializer : alias `place_detail`, `country`, `coords`
- ScheduleSerializer : alias `time` HH:MM + `days` label FR
- SeatMap : champ `code` auto-généré au save, alias `capacity`,
  `usage_count` annoté, delete 409 si utilisé, clone comme plan tenant
"""
from datetime import date, time, timedelta

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from fleet.models import VehicleType
from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.formatting import days_label_fr
from voyage.models import Route, RouteStop, Schedule, SeatMap, Trip
from voyage.serializers import (
    RouteSerializer,
    RouteStopSerializer,
    ScheduleSerializer,
)

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Phase7", slug="phase7-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.p7@toupac.sn", password=PASSWORD,
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
def origin_place(tenant):
    return Place.objects.create(
        tenant=tenant, name="Gare Routière Dakar",
        city="Dakar", country_code="SN",
        type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )


@pytest.fixture
def dest_place(tenant):
    return Place.objects.create(
        tenant=tenant, name="Gare Bamako",
        city="Bamako", country_code="ML",
        type=Place.PlaceType.STATION,
        location=Point(-8.0029, 12.6392, srid=4326),
    )


@pytest.fixture
def route(tenant, origin_place, dest_place):
    return Route.objects.create(
        tenant=tenant, name="Dakar → Bamako",
        code="P7-DKR-BKO",
        origin_place=origin_place, destination_place=dest_place,
    )


# ─── RouteSerializer : o / d ───────────────────────────────────────────


class TestRouteSerializerFlat:
    def test_route_serializer_exposes_o_d_flat(self, route):
        data = RouteSerializer(route).data
        assert data["o"] == "Dakar"
        assert data["d"] == "Bamako"
        # Alias non-breaking : les FK restent exposées.
        assert str(data["origin_place"]) == str(route.origin_place_id)
        assert str(data["destination_place"]) == str(route.destination_place_id)

    def test_route_serializer_o_fallbacks_to_name_when_city_empty(
        self, tenant, dest_place,
    ):
        origin_no_city = Place.objects.create(
            tenant=tenant, name="Dépôt sans ville",
            city="", country_code="SN",
            type=Place.PlaceType.DEPOT,
            location=Point(-17.44, 14.69, srid=4326),
        )
        r = Route.objects.create(
            tenant=tenant, name="Dépôt → BKO", code="P7-NC-BKO",
            origin_place=origin_no_city, destination_place=dest_place,
        )
        data = RouteSerializer(r).data
        assert data["o"] == "Dépôt sans ville"
        assert data["d"] == "Bamako"


# ─── RouteStopSerializer : place_detail / country / coords ──────────────


class TestRouteStopSerializerFlat:
    def test_route_stop_serializer_flat_fields(self, tenant, route, origin_place):
        stop = RouteStop.objects.create(
            tenant=tenant, route=route, place=origin_place,
            stop_order=0, arrival_offset_minutes=0, departure_offset_minutes=0,
        )
        data = RouteStopSerializer(stop).data
        # Alias historique conservé.
        assert data["place_name"] == "Gare Routière Dakar"
        # Aliases Phase 7.
        assert data["place_detail"] == "Gare Routière Dakar"
        assert data["country"] == "SN"
        assert isinstance(data["coords"], list)
        assert len(data["coords"]) == 2
        lng, lat = data["coords"]
        assert lng == pytest.approx(-17.4441, abs=1e-3)
        assert lat == pytest.approx(14.6937, abs=1e-3)


# ─── ScheduleSerializer : time / days ───────────────────────────────────


class TestScheduleSerializerFlat:
    def test_schedule_time_and_days_formatted(self, tenant, route):
        schedule = Schedule.objects.create(
            tenant=tenant, route=route,
            departure_time=time(7, 30),
            days_of_week=[1, 2, 3, 4, 5],
            default_price_xof=15000,
        )
        data = ScheduleSerializer(schedule).data
        assert data["time"] == "07:30"
        assert data["days"] == "Lun-Ven"

    def test_days_label_fr_variants(self):
        assert days_label_fr([1, 2, 3, 4, 5]) == "Lun-Ven"
        assert days_label_fr([6, 7]) == "Weekend"
        assert days_label_fr([1, 2, 3, 4, 5, 6, 7]) == "Tous les jours"
        assert days_label_fr([1, 3, 5]) == "Lun, Mer, Ven"
        assert days_label_fr([]) == ""
        assert days_label_fr(None) == ""


# ─── SeatMap : code auto-généré ─────────────────────────────────────────


class TestSeatMapCode:
    def test_seat_map_code_generated_on_save_with_vehicle_type(self, tenant):
        vt = VehicleType.objects.create(
            tenant=tenant, name="BUS Grand Confort", default_capacity=45,
        )
        sm = SeatMap.objects.create(
            tenant=tenant, name="BUS 45 places", total_seats=45,
            vehicle_type=vt, layout=[],
        )
        # Prefix 4 premiers caractères du nom, en MAJ, strippés.
        assert sm.code == "BUS-45"

    def test_seat_map_code_generated_on_save_without_vehicle_type(self, tenant):
        sm = SeatMap.objects.create(
            tenant=tenant, name="Plan générique", total_seats=45, layout=[],
        )
        assert sm.code == "PLAN-45"

    def test_seat_map_code_is_idempotent(self, tenant):
        sm = SeatMap.objects.create(
            tenant=tenant, name="Plan A", total_seats=10, layout=[],
        )
        assert sm.code == "PLAN-10"
        sm.total_seats = 99
        sm.save()
        # Code non régénéré : stable même si total_seats change.
        assert sm.code == "PLAN-10"


# ─── SeatMap : usage_count annotation + capacity alias ──────────────────


class TestSeatMapAnnotationsViaAPI:
    URL = "/api/v1/voyage/seat-maps/"

    def _make_trip(self, tenant, route, seat_map, internal_id):
        return Trip.objects.create(
            tenant=tenant, route=route, seat_map=seat_map,
            internal_id=internal_id,
            departure_date=date.today() + timedelta(days=1),
            scheduled_at=timezone.now(),
            status=Trip.Status.SCHEDULED,
            total_seats=seat_map.total_seats, booked_seats=0,
        )

    def test_seat_map_usage_count_annotated(
        self, admin_client, tenant, route,
    ):
        sm = SeatMap.objects.create(
            tenant=tenant, name="Plan test", total_seats=20, layout=[],
        )
        self._make_trip(tenant, route, sm, "VYG-P7-UC-01")
        resp = admin_client.get(f"{self.URL}{sm.id}/")
        assert resp.status_code == 200, resp.data
        assert resp.data["usage_count"] == 1
        # Alias Phase 7 — capacity = total_seats.
        assert resp.data["capacity"] == 20
        assert resp.data["code"] == "PLAN-20"

    def test_seat_map_delete_409_if_used(
        self, admin_client, tenant, route,
    ):
        sm = SeatMap.objects.create(
            tenant=tenant, name="Plan utilisé", total_seats=10, layout=[],
        )
        self._make_trip(tenant, route, sm, "VYG-P7-USED-01")
        resp = admin_client.delete(f"{self.URL}{sm.id}/")
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert "utilisé" in str(resp.data).lower()
        # Toujours en base.
        assert SeatMap.objects.filter(pk=sm.pk).exists()


# ─── SeatMap : clone tenant plan ────────────────────────────────────────


class TestSeatMapClone:
    URL = "/api/v1/voyage/seat-maps/"

    def test_seat_map_clone_tenant_plan(self, admin_client, tenant):
        source = SeatMap.objects.create(
            tenant=tenant, name="Plan source", total_seats=12,
            layout=[
                [{"label": "A1"}, {"label": "B1"}],
                [{"label": "A2"}, {"label": "B2"}],
                [{"label": "A3"}, {"label": "B3"}],
                [{"label": "A4"}, {"label": "B4"}],
                [{"label": "A5"}, {"label": "B5"}],
                [{"label": "A6"}, {"label": "B6"}],
            ],
        )
        assert source.code == "PLAN-12"

        resp = admin_client.post(f"{self.URL}{source.id}/clone/", {}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

        clone_id = resp.data["id"]
        clone = SeatMap.objects.get(pk=clone_id)
        # Préservé : tenant courant, layout, total_seats.
        assert clone.tenant_id == tenant.id
        assert clone.total_seats == source.total_seats
        assert clone.layout == source.layout
        # Pas de template clone (plan tenant éditable).
        assert clone.is_template is False
        # `code` régénéré au save du clone (même formule que la source).
        assert clone.code == "PLAN-12"
        # Nom par défaut.
        assert clone.name == f"Copie de {source.name}"
        # Alias Phase 7 présents dans la réponse.
        assert resp.data["capacity"] == 12
        assert resp.data["usage_count"] == 0
