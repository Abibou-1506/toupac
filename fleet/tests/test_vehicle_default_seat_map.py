"""Tests Vehicle.default_seat_map FK (V1.1)."""
import pytest
from rest_framework.test import APIClient

from fleet.models import Vehicle
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import SeatMap

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Vehicle", slug="vehicle-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.vehicle@toupac.sn", password=PASSWORD,
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
        tenant=tenant, name="Sprinter default", total_seats=0, layout=[],
    )


class TestVehicleDefaultSeatMap:
    def test_vehicle_can_have_default_seat_map(self, tenant, seat_map):
        v = Vehicle.objects.create(
            tenant=tenant, plate_number="SN-1234",
            capacity=45, default_seat_map=seat_map,
        )
        assert v.default_seat_map == seat_map

    def test_vehicle_default_seat_map_set_null_on_delete(self, tenant, seat_map):
        v = Vehicle.objects.create(
            tenant=tenant, plate_number="SN-5678",
            capacity=45, default_seat_map=seat_map,
        )
        seat_map.delete()
        v.refresh_from_db()
        assert v.default_seat_map is None

    def test_vehicle_api_exposes_default_seat_map(
        self, admin_client, tenant, seat_map,
    ):
        v = Vehicle.objects.create(
            tenant=tenant, plate_number="SN-9999",
            capacity=45, default_seat_map=seat_map,
        )
        response = admin_client.get(f"/api/v1/fleet/vehicles/{v.id}/")
        assert response.status_code == 200
        # DRF retourne un UUID instance pour les PK UUID — on compare par
        # string pour rester agnostique à la représentation.
        assert str(response.data["default_seat_map"]) == str(seat_map.id)
