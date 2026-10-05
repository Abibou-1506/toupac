"""
TOUPAC Billing — PaymentViewSet : lecture seule, filtres, isolation tenant.

L'endpoint est consommé par le backoffice web pour l'écran /paiements.
La création d'un paiement reste sur /payments/initiate/ (mobile money).
"""
import pytest
from rest_framework.test import APIClient

from billing.models import Payment
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Pay", slug="pay-tenant")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Autre Transport", slug="pay-other")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.pay@toupac.sn", password=PASSWORD,
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
def make_payment(tenant):
    """Factory : `make_payment(status=..., provider=..., amount_xof=...)`."""
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = {
            "tenant": tenant,
            "provider": Payment.Provider.WAVE,
            "amount_xof": 5000,
            "status": Payment.Status.SUCCESS,
            "provider_tx_id": f"TX-PAY-{counter['n']:03d}",
        }
        defaults.update(kwargs)
        return Payment.objects.create(**defaults)

    return _make


# ─── Tests ───

def test_list_payments_tenant_isolated(admin_client, make_payment, other_tenant):
    """Un admin voit uniquement les paiements de son tenant."""
    own = make_payment()
    Payment.objects.create(
        tenant=other_tenant, provider=Payment.Provider.ORANGE_MONEY,
        amount_xof=9999, status=Payment.Status.SUCCESS,
        provider_tx_id="TX-OTHER-TENANT",
    )

    response = admin_client.get("/api/v1/billing/payments/")
    assert response.status_code == 200
    ids = {item["id"] for item in response.data["results"]}
    assert str(own.id) in ids
    assert len(ids) == 1


def test_filter_by_status(admin_client, make_payment):
    """Filtre ?status=success."""
    make_payment(status=Payment.Status.SUCCESS)
    make_payment(status=Payment.Status.FAILED)
    response = admin_client.get("/api/v1/billing/payments/?status=success")
    assert response.status_code == 200
    for item in response.data["results"]:
        assert item["status"] == "success"
    assert any(item["status"] == "success" for item in response.data["results"])


def test_filter_by_provider(admin_client, make_payment):
    """Filtre ?provider=wave."""
    make_payment(provider=Payment.Provider.WAVE)
    make_payment(provider=Payment.Provider.ORANGE_MONEY)
    response = admin_client.get("/api/v1/billing/payments/?provider=wave")
    assert response.status_code == 200
    for item in response.data["results"]:
        assert item["provider"] == "wave"
    assert any(item["provider"] == "wave" for item in response.data["results"])


def test_retrieve_payment(admin_client, make_payment):
    """Détail d'un paiement retourne tous les champs."""
    payment = make_payment(amount_xof=12345)
    response = admin_client.get(f"/api/v1/billing/payments/{payment.id}/")
    assert response.status_code == 200
    assert response.data["amount_xof"] == 12345
    assert response.data["provider_tx_id"] == payment.provider_tx_id


def test_write_methods_not_allowed(admin_client, make_payment):
    """POST/PUT/DELETE renvoient 405 (ReadOnlyModelViewSet).

    `/payments/initiate/` reste accessible pour créer des paiements mobile
    money ; c'est /payments/ (le ViewSet) qui doit interdire les écritures.
    """
    payment = make_payment()
    assert admin_client.post("/api/v1/billing/payments/", {}, format="json").status_code == 405
    assert admin_client.put(f"/api/v1/billing/payments/{payment.id}/", {}, format="json").status_code == 405
    assert admin_client.delete(f"/api/v1/billing/payments/{payment.id}/").status_code == 405


def test_initiate_still_reachable(admin_client):
    """Vérifie que /payments/initiate/ n'est pas masqué par le router /payments/.

    Les paths explicites /payments/initiate/ et /payments/webhook/ doivent
    résoudre vers leurs vues APIView dédiées, pas vers le ViewSet (sinon
    "initiate" serait interprété comme un pk UUID → 404 ou erreur de parse).
    """
    # Payload invalide volontairement : on cherche la vue qui doit répondre
    # ≠ 404 et ≠ 405 (donc une validation DRF).
    response = admin_client.post("/api/v1/billing/payments/initiate/", {}, format="json")
    assert response.status_code != 404
    assert response.status_code != 405
