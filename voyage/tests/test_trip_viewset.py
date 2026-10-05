"""Tests TripViewSet create — internal_id auto + summary read_only.

Débloque les Sheets V1.1 du backoffice toupac-web : POST sans
internal_id doit générer un identifiant au format
T-{PREFIX}-{YYYYMMDD}-{NN} ; `summary` fourni au payload est ignoré
(read_only, calculé à la clôture de session de contrôle).
"""
from datetime import date, time, timedelta

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, SeatMap, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Trip", slug="trip-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.trip@toupac.sn", password=PASSWORD,
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
def route(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    return Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS-TRIP",
        origin_place=origin, destination_place=destination,
    )


@pytest.fixture
def seat_map(tenant):
    return SeatMap.objects.create(
        tenant=tenant, name="Sprinter 45", total_seats=45, layout={},
    )


# ─── Tests ───

class TestTripCreate:
    URL = "/api/v1/voyage/trips/"

    def _base_payload(self, route, seat_map, **overrides):
        tomorrow = date.today() + timedelta(days=1)
        scheduled = timezone.make_aware(
            timezone.datetime.combine(tomorrow, time(8, 0))
        )
        payload = {
            "route": str(route.id),
            "seat_map": str(seat_map.id),
            "departure_date": tomorrow.isoformat(),
            "scheduled_at": scheduled.isoformat(),
            "total_seats": 45,
            "status": "scheduled",
        }
        payload.update(overrides)
        return payload

    def test_create_with_auto_internal_id(self, admin_client, route, seat_map):
        """Un POST sans internal_id le génère au format T-{PREFIX}-{DATE}-{NN}."""
        response = admin_client.post(
            self.URL,
            self._base_payload(route, seat_map),
            format="json",
        )
        assert response.status_code == 201, response.data
        internal_id = response.data["internal_id"]
        today_str = date.today().strftime("%Y%m%d")
        assert internal_id.startswith("T-")
        assert today_str in internal_id
        parts = internal_id.split("-")
        assert len(parts) == 4
        assert parts[-1].isdigit()

    def test_summary_is_read_only_on_create(self, admin_client, route, seat_map):
        """Un `summary` fourni au POST est ignoré (read_only)."""
        payload = self._base_payload(
            route, seat_map,
            summary={"fake": "attempt"},
        )
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == 201, response.data
        trip_id = response.data["id"]
        trip = Trip.objects.get(id=trip_id)
        # summary vide à la création, pas la valeur fournie dans le payload
        assert trip.summary in (None, {})

    def test_sequential_internal_ids_same_day(self, admin_client, route, seat_map):
        """Deux POST séquentiels même jour → index incrémenté."""
        payload = self._base_payload(route, seat_map)
        r1 = admin_client.post(self.URL, payload, format="json")
        r2 = admin_client.post(self.URL, payload, format="json")
        assert r1.status_code == 201, r1.data
        assert r2.status_code == 201, r2.data
        id1 = r1.data["internal_id"]
        id2 = r2.data["internal_id"]
        assert id1 != id2
        assert id1.rsplit("-", 1)[0] == id2.rsplit("-", 1)[0]
        idx1 = int(id1.rsplit("-", 1)[1])
        idx2 = int(id2.rsplit("-", 1)[1])
        assert idx2 == idx1 + 1

    def test_create_with_explicit_internal_id(self, admin_client, route, seat_map):
        """Si internal_id fourni explicitement (apps RN mobiles), il est respecté."""
        payload = self._base_payload(
            route, seat_map, internal_id="T-CUSTOM-001",
        )
        response = admin_client.post(self.URL, payload, format="json")
        assert response.status_code == 201, response.data
        assert response.data["internal_id"] == "T-CUSTOM-001"
