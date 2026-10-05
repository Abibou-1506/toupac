"""Tests RouteStopSerializer expose place_location as GeoJSON Point (V1.1).

Débloque l'animation Leaflet polyline sur la page création voyage du
backoffice web : à la sélection d'une route, le front doit pouvoir tracer
les stops et une polyline sans appel supplémentaire.
"""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, RouteStop

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Route", slug="route-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.route@toupac.sn", password=PASSWORD,
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
def route_with_stops(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    intermediate = Place.objects.create(
        tenant=tenant, name="Kaolack", type=Place.PlaceType.STATION,
        location=Point(-16.07, 14.17, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Thiès via Kaolack", code="DKR-THS-STOPS",
        origin_place=origin, destination_place=destination,
    )
    RouteStop.objects.create(tenant=tenant, route=route, place=origin, stop_order=0)
    RouteStop.objects.create(tenant=tenant, route=route, place=intermediate, stop_order=1)
    RouteStop.objects.create(tenant=tenant, route=route, place=destination, stop_order=2)
    return route


def test_route_detail_includes_stops_with_coordinates(
    admin_client, route_with_stops,
):
    response = admin_client.get(f"/api/v1/voyage/routes/{route_with_stops.id}/")
    assert response.status_code == 200, response.data
    stops = response.data["stops"]
    assert len(stops) == 3
    # Trier par stop_order pour tests déterministes.
    stops = sorted(stops, key=lambda s: s["stop_order"])
    assert stops[0]["place_name"] == "Dakar"
    assert stops[2]["place_name"] == "Thiès"
    for stop in stops:
        assert "place_location" in stop
        gps = stop["place_location"]
        assert gps is not None
        assert gps["type"] == "Point"
        assert len(gps["coordinates"]) == 2
    # Vérifie une coordonnée précise (Dakar).
    dakar = stops[0]
    assert pytest.approx(dakar["place_location"]["coordinates"][0], abs=0.01) == -17.44
    assert pytest.approx(dakar["place_location"]["coordinates"][1], abs=0.01) == 14.69
