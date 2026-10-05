"""Tests endpoints Dashboard."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from billing.models import Payment
from colis.models import Order
from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Incident, Passenger, Reservation, Route, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Dash", slug="dash-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre Transport", slug="dash-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.dash@toupac.sn", password=PASSWORD,
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
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS-DASH",
        origin_place=origin, destination_place=destination,
    )


@pytest.fixture
def make_trip(tenant, route):
    """Factory: `make_trip(departure_date=..., status=..., actual_departure_at=...)`."""
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = {
            "tenant": tenant,
            "route": route,
            "internal_id": f"VYG-DASH-{counter['n']:03d}",
            "departure_date": timezone.now().date(),
            "scheduled_at": timezone.now(),
            "status": Trip.Status.SCHEDULED,
            "total_seats": 40,
            "booked_seats": 0,
        }
        defaults.update(kwargs)
        return Trip.objects.create(**defaults)

    return _make


# ─── KPIs ───

class TestDashboardKPIs:
    URL = "/api/v1/dashboard/kpis/"

    def test_returns_four_kpis(self, admin_client):
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        assert "voyagesAujourdhui" in response.data
        assert "commandesEnCours" in response.data
        assert "incidentsOuverts" in response.data
        assert "caDuMois" in response.data

    def test_kpi_structure(self, admin_client):
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        kpi = response.data["voyagesAujourdhui"]
        assert "value" in kpi
        assert "trend" in kpi
        assert "trendTone" in kpi
        assert kpi["trendTone"] in {"success", "warning", "danger", "neutral"}

    def test_trips_today_count(self, admin_client, make_trip):
        today = timezone.now().date()
        make_trip(departure_date=today)
        make_trip(departure_date=today)
        make_trip(departure_date=today - timedelta(days=5))
        response = admin_client.get(self.URL)
        assert response.data["voyagesAujourdhui"]["value"] == 2

    def test_orders_in_progress_count(self, admin_client, tenant, route):
        pickup = Place.objects.create(
            tenant=tenant, name="A", type=Place.PlaceType.STATION,
            location=Point(-17.0, 14.0, srid=4326),
        )
        dropoff = Place.objects.create(
            tenant=tenant, name="B", type=Place.PlaceType.STATION,
            location=Point(-16.0, 14.5, srid=4326),
        )
        Order.objects.create(
            tenant=tenant, internal_id="CMD-DASH-01",
            pickup_place=pickup, dropoff_place=dropoff,
            status=Order.Status.IN_TRANSIT, total_amount_xof=5000,
        )
        Order.objects.create(
            tenant=tenant, internal_id="CMD-DASH-02",
            pickup_place=pickup, dropoff_place=dropoff,
            status=Order.Status.DISPATCHED, total_amount_xof=5000,
        )
        Order.objects.create(
            tenant=tenant, internal_id="CMD-DASH-03",
            pickup_place=pickup, dropoff_place=dropoff,
            status=Order.Status.DELIVERED, total_amount_xof=5000,
        )
        response = admin_client.get(self.URL)
        assert response.data["commandesEnCours"]["value"] == 2
        assert "1 en transit" in response.data["commandesEnCours"]["trend"]
        assert "1 à livrer" in response.data["commandesEnCours"]["trend"]

    def test_tenant_isolation_trips(self, admin_client, make_trip, other_tenant):
        """Les KPIs du tenant courant n'incluent pas les trips d'un autre tenant."""
        today = timezone.now().date()
        make_trip(departure_date=today)
        other_origin = Place.objects.create(
            tenant=other_tenant, name="OtherA", type=Place.PlaceType.STATION,
            location=Point(-15.0, 13.0, srid=4326),
        )
        other_dest = Place.objects.create(
            tenant=other_tenant, name="OtherB", type=Place.PlaceType.STATION,
            location=Point(-14.0, 13.5, srid=4326),
        )
        other_route = Route.objects.create(
            tenant=other_tenant, name="X → Y", code="XY-DASH",
            origin_place=other_origin, destination_place=other_dest,
        )
        Trip.objects.create(
            tenant=other_tenant, route=other_route,
            internal_id="VYG-OTHER-DASH", departure_date=today,
            scheduled_at=timezone.now(),
            status=Trip.Status.SCHEDULED, total_seats=10, booked_seats=0,
        )
        response = admin_client.get(self.URL)
        # Un seul trip du tenant courant doit être compté.
        assert response.data["voyagesAujourdhui"]["value"] == 1


# ─── Activities ───

class TestDashboardActivities:
    URL = "/api/v1/dashboard/activities/"

    def test_returns_list_capped_at_20(self, admin_client):
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        assert isinstance(response.data, list)
        assert len(response.data) <= 20

    def test_activity_structure(self, admin_client, make_trip):
        make_trip(actual_departure_at=timezone.now(), status=Trip.Status.IN_TRANSIT)
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        assert len(response.data) >= 1
        activity = response.data[0]
        assert "id" in activity
        assert "type" in activity
        assert "description" in activity
        assert "timestamp" in activity
        assert "linkTo" in activity
        assert activity["type"] in {
            "voyage", "paiement", "incident", "commande", "reservation",
        }

    def test_sorted_by_timestamp_desc(self, admin_client, make_trip):
        now = timezone.now()
        make_trip(actual_departure_at=now - timedelta(hours=2), status=Trip.Status.IN_TRANSIT)
        make_trip(actual_departure_at=now - timedelta(hours=1), status=Trip.Status.IN_TRANSIT)
        make_trip(actual_departure_at=now, status=Trip.Status.IN_TRANSIT)
        response = admin_client.get(self.URL)
        trip_activities = [a for a in response.data if a["type"] == "voyage"]
        assert len(trip_activities) >= 3
        timestamps = [a["timestamp"] for a in trip_activities]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_payment_activity_formatting(self, admin_client, tenant):
        Payment.objects.create(
            tenant=tenant,
            provider=Payment.Provider.WAVE,
            amount_xof=25000,
            status=Payment.Status.SUCCESS,
            completed_at=timezone.now(),
            provider_tx_id="TX-DASH-PAY-001",
        )
        response = admin_client.get(self.URL)
        payment_activities = [a for a in response.data if a["type"] == "paiement"]
        assert len(payment_activities) == 1
        activity = payment_activities[0]
        assert "25 000 XOF" in activity["description"]
        assert "Wave" in activity["description"]
        assert activity["linkTo"] == "/paiements"
