"""Tests DriverSerializer flat full_name / user_phone / user_email (V1.1)."""
import pytest
from rest_framework.test import APIClient

from fleet.models import Driver
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Driver", slug="driver-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.driver@toupac.sn", password=PASSWORD,
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
def driver(tenant):
    user = User.objects.create_user(
        email="moussa.driver@toupac.sn", password=PASSWORD,
        first_name="Moussa", last_name="Diallo", phone="+221771234567",
        tenant=tenant, role=User.Role.DRIVER,
    )
    return Driver.objects.create(
        tenant=tenant, user=user, license_number="SN-DL-TEST-01",
    )


class TestDriverFlatFields:
    def test_list_exposes_flat_full_name(self, admin_client, driver):
        response = admin_client.get("/api/v1/fleet/drivers/")
        assert response.status_code == 200
        row = next(r for r in response.data["results"] if r["id"] == str(driver.id))
        assert row["full_name"] == "Moussa Diallo"
        assert row["user_phone"] == "+221771234567"
        assert row["user_email"] == "moussa.driver@toupac.sn"

    def test_nested_user_preserved_for_rn(self, admin_client, driver):
        """`driver.user` nesté reste exposé pour compat RN mobile."""
        response = admin_client.get("/api/v1/fleet/drivers/")
        row = next(r for r in response.data["results"] if r["id"] == str(driver.id))
        assert "user" in row
        assert row["user"]["full_name"] == "Moussa Diallo"
