"""Tests SeatMapViewSet — lecture seule, isolation tenant, détail layout.

L'endpoint `/api/v1/voyage/seat-maps/` est consommé par le Sheet
'Nouveau voyage' du backoffice web pour choisir un plan existant. Les
apps mobiles RN ne l'utilisent pas (elles consomment `seat_map` niché
dans ManifestSerializer).
"""
import pytest
from rest_framework.test import APIClient

from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import SeatMap

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


# ─── Tests ───

class TestSeatMapViewSet:
    URL = "/api/v1/voyage/seat-maps/"

    def test_list_tenant_isolated(self, admin_client, tenant, other_tenant):
        own = SeatMap.objects.create(
            tenant=tenant, name="Sprinter 45", total_seats=45,
            layout={"rows": 10},
        )
        SeatMap.objects.create(
            tenant=other_tenant, name="Yutong 55", total_seats=55, layout={},
        )
        response = admin_client.get(self.URL)
        assert response.status_code == 200
        ids = {item["id"] for item in response.data["results"]}
        assert str(own.id) in ids
        assert len(ids) == 1

    def test_retrieve_includes_layout(self, admin_client, tenant):
        sm = SeatMap.objects.create(
            tenant=tenant, name="Coaster 30", total_seats=30,
            layout={"rows": 8, "cols": 4},
        )
        response = admin_client.get(f"{self.URL}{sm.id}/")
        assert response.status_code == 200
        assert "layout" in response.data
        assert response.data["layout"] == {"rows": 8, "cols": 4}
        assert response.data["total_seats"] == 30

    def test_write_methods_not_allowed(self, admin_client, tenant):
        """POST/PUT/DELETE renvoient 405 (ReadOnlyModelViewSet)."""
        sm = SeatMap.objects.create(
            tenant=tenant, name="Bus 50", total_seats=50, layout={},
        )
        assert admin_client.post(self.URL, {}, format="json").status_code == 405
        assert admin_client.put(f"{self.URL}{sm.id}/", {}, format="json").status_code == 405
        assert admin_client.delete(f"{self.URL}{sm.id}/").status_code == 405
