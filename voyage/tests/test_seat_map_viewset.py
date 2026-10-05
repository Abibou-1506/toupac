"""Tests SeatMapViewSet — full CRUD depuis V1.1 + validations layout."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, SeatMap, Trip
from geo.models import Place
from django.contrib.gis.geos import Point
from django.utils import timezone
from datetime import date, timedelta

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Seat", slug="seat-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre Transport", slug="seat-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.seat@toupac.sn", password=PASSWORD,
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
def seat_map(tenant):
    return SeatMap.objects.create(
        tenant=tenant, name="Sprinter 45", total_seats=4,
        layout=[
            [{"label": "A1"}, {"label": "B1"}],
            [{"label": "A2"}, {"label": "B2"}],
        ],
    )


# ─── Tests lecture (préexistants) ───

class TestSeatMapRead:
    URL = "/api/v1/voyage/seat-maps/"

    def test_list_tenant_isolated(self, admin_client, tenant, other_tenant):
        own = SeatMap.objects.create(
            tenant=tenant, name="Local 45", total_seats=0, layout=[],
        )
        SeatMap.objects.create(
            tenant=other_tenant, name="Yutong 55", total_seats=0, layout=[],
        )
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        ids = {item["id"] for item in response.data["results"]}
        assert str(own.id) in ids
        assert len(ids) == 1

    def test_retrieve_includes_layout(self, admin_client, seat_map):
        response = admin_client.get(f"{self.URL}{seat_map.id}/")
        assert response.status_code == 200
        assert response.data["total_seats"] == 4
        assert len(response.data["layout"]) == 2


# ─── Tests CRUD V1.1 ───

class TestSeatMapCRUD:
    URL = "/api/v1/voyage/seat-maps/"

    def test_create_valid_layout(self, admin_client):
        # 12 cellules "seat" (A1, B1, C1, D1, A2, B2, C2, D2, E1, E2, E3, E4)
        # + 1 cellule type "driver" (hors comptage) + plusieurs None.
        payload = {
            "name": "Bus 12 places test",
            "total_seats": 12,
            "layout": [
                [{"label": "A1"}, {"label": "B1"}, None, {"label": "C1"}, {"label": "D1"}],
                [{"label": "A2"}, {"label": "B2"}, None, {"label": "C2"}, {"label": "D2"}],
                [{"label": "E1"}, {"label": "E2"}, {"label": "E3"}, {"label": "E4"}, None],
                [{"label": "DRV", "type": "driver"}, None, None, None, None],
            ],
        }
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        # Driver cell n'est pas comptée dans total_seats.
        assert response.data["total_seats"] == 12

    def test_create_rejects_non_rectangular_layout(self, admin_client):
        payload = {
            "name": "Bus bancal",
            "total_seats": 3,
            "layout": [
                [{"label": "A1"}, {"label": "B1"}],
                [{"label": "A2"}],
            ],
        }
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == 400
        assert "rangées" in str(response.data).lower()

    def test_create_rejects_duplicate_label(self, admin_client):
        payload = {
            "name": "Doublon",
            "total_seats": 2,
            "layout": [
                [{"label": "A1"}, {"label": "A1"}],
            ],
        }
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == 400
        assert "dupliqué" in str(response.data).lower() or "duplic" in str(response.data).lower()

    def test_create_rejects_total_seats_mismatch(self, admin_client):
        payload = {
            "name": "Incohérent",
            "total_seats": 5,
            "layout": [
                [{"label": "A1"}, {"label": "B1"}, {"label": "C1"}],
            ],
        }
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == 400
        assert "total_seats" in response.data

    def test_update_seat_map_name(self, admin_client, seat_map):
        response = admin_client.patch(
            f"{self.URL}{seat_map.id}/",
            {"name": "Nouveau nom"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["name"] == "Nouveau nom"

    def test_delete_unused_seat_map(self, admin_client, seat_map):
        response = admin_client.delete(f"{self.URL}{seat_map.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_used_seat_map_refused(self, admin_client, tenant, seat_map):
        """DELETE d'un plan utilisé par un trip renvoie 409."""
        origin = Place.objects.create(
            tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
            location=Point(-17.44, 14.69, srid=4326),
        )
        dest = Place.objects.create(
            tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
            location=Point(-16.92, 14.78, srid=4326),
        )
        route = Route.objects.create(
            tenant=tenant, name="Dakar → Thiès", code="DKR-THS-SM",
            origin_place=origin, destination_place=dest,
        )
        Trip.objects.create(
            tenant=tenant, route=route, seat_map=seat_map,
            internal_id="VYG-SM-01",
            departure_date=date.today() + timedelta(days=1),
            scheduled_at=timezone.now(),
            status=Trip.Status.SCHEDULED, total_seats=4, booked_seats=0,
        )
        response = admin_client.delete(f"{self.URL}{seat_map.id}/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "utilisé" in str(response.data).lower()
