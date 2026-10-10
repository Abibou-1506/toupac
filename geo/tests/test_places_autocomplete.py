"""Phase 7 — autocomplete tenant-scopé /geo/places/autocomplete/?q=…

Alimente le StopsEditor du backoffice web (Routes.jsx) : search par nom /
ville / adresse, max 20 résultats, format compact {id, name, city,
country_code, coords}.
"""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"
URL = "/api/v1/geo/places/autocomplete/"


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport AC", slug="ac-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre AC", slug="ac-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.ac@toupac.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_place(tenant, name, city="", country="SN"):
    return Place.objects.create(
        tenant=tenant, name=name, city=city, country_code=country,
        type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )


# ─── Tests ──────────────────────────────────────────────────────────────


class TestPlacesAutocomplete:
    def test_geo_places_autocomplete_compact_format(self, admin_client, tenant):
        _make_place(tenant, "Gare Routière Dakar", city="Dakar")
        resp = admin_client.get(f"{URL}?q=Dakar")
        assert resp.status_code == 200, resp.data
        assert isinstance(resp.data, list)
        assert len(resp.data) == 1
        item = resp.data[0]
        # Format compact — pas de metadata / tenant / type.
        assert set(item.keys()) == {"id", "name", "city", "country_code", "coords"}
        assert item["name"] == "Gare Routière Dakar"
        assert item["city"] == "Dakar"
        assert item["country_code"] == "SN"
        assert item["coords"] == [pytest.approx(-17.44), pytest.approx(14.69)]

    def test_geo_places_autocomplete_matches_name_or_city_or_address(
        self, admin_client, tenant,
    ):
        _make_place(tenant, "Gare Dakar", city="Dakar")
        _make_place(tenant, "Agence Thiès", city="Thiès")
        _make_place(tenant, "Dépôt principal", city="Pikine")

        # Match sur name.
        resp = admin_client.get(f"{URL}?q=Agence")
        names = [p["name"] for p in resp.data]
        assert names == ["Agence Thiès"]

        # Match sur city.
        resp = admin_client.get(f"{URL}?q=Pikine")
        names = [p["name"] for p in resp.data]
        assert names == ["Dépôt principal"]

        # Insensible à la casse.
        resp = admin_client.get(f"{URL}?q=dakar")
        names = [p["name"] for p in resp.data]
        assert names == ["Gare Dakar"]

    def test_geo_places_autocomplete_tenant_scoped(
        self, admin_client, tenant, other_tenant,
    ):
        _make_place(tenant, "Gare Dakar Tenant A", city="Dakar")
        _make_place(other_tenant, "Gare Dakar Tenant B", city="Dakar")
        resp = admin_client.get(f"{URL}?q=Dakar")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.data]
        # Place `tenant=NULL` partagée reste visible (gares publiques) ;
        # ici aucune de ce type n'est créée, donc seul le tenant courant
        # remonte.
        assert "Gare Dakar Tenant A" in names
        assert "Gare Dakar Tenant B" not in names

    def test_geo_places_autocomplete_shared_places_visible(self, admin_client):
        """Les Places `tenant=NULL` (gares publiques) remontent pour tous."""
        shared = Place.objects.create(
            tenant=None, name="Gare publique Dakar", city="Dakar",
            country_code="SN", type=Place.PlaceType.STATION,
            location=Point(-17.44, 14.69, srid=4326),
        )
        resp = admin_client.get(f"{URL}?q=publique")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.data]
        assert str(shared.id) in ids

    def test_geo_places_autocomplete_bounded_to_20(self, admin_client, tenant):
        for i in range(25):
            _make_place(tenant, f"Gare Zulu {i:02d}", city="Zulu")
        resp = admin_client.get(f"{URL}?q=Zulu")
        assert resp.status_code == 200
        assert len(resp.data) == 20

    def test_geo_places_autocomplete_empty_q_returns_up_to_20(
        self, admin_client, tenant,
    ):
        """q vide → remonte quand même les 20 premières places du tenant."""
        _make_place(tenant, "AAA Un", city="X")
        _make_place(tenant, "BBB Deux", city="X")
        resp = admin_client.get(URL)
        assert resp.status_code == 200
        assert len(resp.data) <= 20
        names = {p["name"] for p in resp.data}
        assert {"AAA Un", "BBB Deux"} <= names
