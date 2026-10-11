"""Tests LuggagePolicyViewSet — CRUD + isolation tenant (dette V1.1 Vague 3).

L'endpoint `/api/v1/voyage/luggage-policies/` alimente le combobox
"+ Créer" du frontend VehicleTypeDetailPage (FK `default_luggage_policy`)
et le selecteur Routes.jsx (FK `luggage_policy` sur Route).
"""
import pytest
from rest_framework.test import APIClient

from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import LuggagePolicy

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"
URL = "/api/v1/voyage/luggage-policies/"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport LP", slug="lp-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre LP", slug="lp-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.lp@toupac.sn", password=PASSWORD,
        first_name="Admin", last_name="LP",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def client(admin_user):
    c = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_user).access_token)
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


# ─── CRUD ───

def test_create_luggage_policy(client, tenant):
    response = client.post(
        URL,
        {
            "name": "Standard",
            "included_kg": 20,
            "max_kg": 30,
            "excess_price_per_kg_xof": 500,
            "max_pieces": 2,
            "restricted_items": ["armes", "produits inflammables"],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.data["name"] == "Standard"
    assert response.data["included_kg"] == 20
    assert response.data["restricted_items"] == ["armes", "produits inflammables"]
    # Tenant est injecté par la vue, pas lu depuis le payload.
    assert LuggagePolicy.objects.get(id=response.data["id"]).tenant_id == tenant.id


def test_list_luggage_policy_tenant_scoped(client, tenant, other_tenant):
    LuggagePolicy.objects.create(
        tenant=tenant, name="Standard", included_kg=10, max_kg=20,
        excess_price_per_kg_xof=100, max_pieces=1,
    )
    LuggagePolicy.objects.create(
        tenant=other_tenant, name="Hidden", included_kg=10, max_kg=20,
        excess_price_per_kg_xof=100, max_pieces=1,
    )
    response = client.get(URL)
    assert response.status_code == 200
    names = [p["name"] for p in response.data["results"]]
    assert "Standard" in names
    assert "Hidden" not in names


def test_update_luggage_policy(client, tenant):
    policy = LuggagePolicy.objects.create(
        tenant=tenant, name="Original", included_kg=10, max_kg=20,
        excess_price_per_kg_xof=100, max_pieces=1,
    )
    response = client.patch(
        f"{URL}{policy.id}/",
        {"name": "Updated", "max_kg": 35},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["name"] == "Updated"
    assert response.data["max_kg"] == 35
    policy.refresh_from_db()
    assert policy.name == "Updated"
    assert policy.max_kg == 35


def test_delete_luggage_policy(client, tenant):
    policy = LuggagePolicy.objects.create(
        tenant=tenant, name="Delete me", included_kg=10, max_kg=20,
        excess_price_per_kg_xof=100, max_pieces=1,
    )
    response = client.delete(f"{URL}{policy.id}/")
    assert response.status_code == 204
    assert not LuggagePolicy.objects.filter(id=policy.id).exists()


def test_unauthenticated_rejected():
    # Sans JWT : pas de tenant résolu par TenantMiddleware, pas d'auth DRF.
    c = APIClient()
    response = c.get(URL)
    assert response.status_code in (401, 403)
