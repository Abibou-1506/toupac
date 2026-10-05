"""
TOUPAC Voyage — IncidentViewSet : lecture seule, filtres, isolation tenant.

L'endpoint est consommé par le backoffice web pour l'écran /incidents.
Les incidents sont créés par les contrôleurs via le batch sync offline ;
le ViewSet web n'expose que la lecture.
"""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Incident, Route, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Inc", slug="inc-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre Transport", slug="inc-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.inc@toupac.sn", password=PASSWORD,
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
def trip(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS-INC",
        origin_place=origin, destination_place=destination,
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-INC-01",
        departure_date="2026-10-10", scheduled_at="2026-10-10T07:00:00Z",
        status=Trip.Status.COMPLETED, total_seats=40, booked_seats=35,
    )


@pytest.fixture
def make_incident(tenant, trip, admin_user):
    """Factory : `make_incident(status=..., severity=..., type=...)`."""
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = {
            "tenant": tenant,
            "trip": trip,
            "reporter": admin_user,
            "type": Incident.Type.LUGGAGE,
            "severity": Incident.Severity.LOW,
            "status": Incident.Status.REPORTED,
            "title": f"Incident test #{counter['n']}",
        }
        defaults.update(kwargs)
        return Incident.objects.create(**defaults)

    return _make


# ─── Tests ───

def test_list_incidents_tenant_isolated(admin_client, make_incident, other_tenant, admin_user):
    """Un admin voit uniquement les incidents de son tenant."""
    own = make_incident()
    # Un incident sur un autre tenant ne doit pas apparaître.
    other_origin = Place.objects.create(
        tenant=other_tenant, name="OtherA", type=Place.PlaceType.STATION,
        location=Point(-17.0, 14.0, srid=4326),
    )
    other_dest = Place.objects.create(
        tenant=other_tenant, name="OtherB", type=Place.PlaceType.STATION,
        location=Point(-16.0, 14.5, srid=4326),
    )
    other_route = Route.objects.create(
        tenant=other_tenant, name="X → Y", code="XY-OTHER",
        origin_place=other_origin, destination_place=other_dest,
    )
    other_trip = Trip.objects.create(
        tenant=other_tenant, route=other_route, internal_id="VYG-OTHER",
        departure_date="2026-10-10", scheduled_at="2026-10-10T07:00:00Z",
        status=Trip.Status.COMPLETED, total_seats=10, booked_seats=0,
    )
    Incident.objects.create(
        tenant=other_tenant, trip=other_trip, reporter=admin_user,
        type=Incident.Type.OTHER, severity=Incident.Severity.LOW,
        status=Incident.Status.REPORTED, title="Hors tenant",
    )

    response = admin_client.get("/api/v1/voyage/incidents/")
    assert response.status_code == 200
    ids = {item["id"] for item in response.data["results"]}
    assert str(own.id) in ids
    assert len(ids) == 1


def test_filter_by_status(admin_client, make_incident):
    """Filtre ?status=resolved."""
    make_incident(status=Incident.Status.RESOLVED)
    make_incident(status=Incident.Status.REPORTED)
    response = admin_client.get("/api/v1/voyage/incidents/?status=resolved")
    assert response.status_code == 200
    for item in response.data["results"]:
        assert item["status"] == "resolved"
    assert any(item["status"] == "resolved" for item in response.data["results"])


def test_filter_by_severity(admin_client, make_incident):
    """Filtre ?severity=critical."""
    make_incident(severity=Incident.Severity.CRITICAL)
    make_incident(severity=Incident.Severity.LOW)
    response = admin_client.get("/api/v1/voyage/incidents/?severity=critical")
    assert response.status_code == 200
    for item in response.data["results"]:
        assert item["severity"] == "critical"
    assert any(item["severity"] == "critical" for item in response.data["results"])


def test_retrieve_incident_returns_detail_fields(admin_client, make_incident):
    """Détail d'un incident retourne les champs du DetailSerializer."""
    incident = make_incident(status=Incident.Status.IN_PROGRESS)
    response = admin_client.get(f"/api/v1/voyage/incidents/{incident.id}/")
    assert response.status_code == 200
    # Champs ajoutés par le DetailSerializer vs ListSerializer :
    assert "description" in response.data
    assert "photos_urls" in response.data
    assert "gps_address" in response.data
    # Et les champs communs :
    assert response.data["title"] == incident.title
    assert response.data["trip_internal_id"] == "VYG-INC-01"


def test_write_methods_not_allowed(admin_client, make_incident):
    """POST/PUT/DELETE renvoient 405 (ReadOnlyModelViewSet)."""
    incident = make_incident()
    assert admin_client.post("/api/v1/voyage/incidents/", {}, format="json").status_code == 405
    assert admin_client.put(f"/api/v1/voyage/incidents/{incident.id}/", {}, format="json").status_code == 405
    assert admin_client.delete(f"/api/v1/voyage/incidents/{incident.id}/").status_code == 405
