"""
TOUPAC IAM — `/customer/my-orders/`, les colis commandés par le client.

Le lien est direct (`Order.customer`) et désigne le **commanditaire**. Un client
destinataire d'un colis expédié par quelqu'un d'autre ne le voit pas : asymétrie
assumée en V1, tracée dans DETTES.md. Un test la fige pour qu'elle reste un
choix visible plutôt qu'un oubli.
"""
import pytest

from colis.models import Order
from iam.models import User
from iam.tests.customer_factories import make_order

pytestmark = pytest.mark.django_db

URL = "/api/v1/customer/my-orders/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def get(authenticated_client, user, query=""):
    return authenticated_client(user).get(f"{URL}{query}")


def test_returns_empty_when_no_orders(authenticated_client, client_fatou):
    response = get(authenticated_client, client_fatou)

    assert response.status_code == 200
    assert response.json()["orders"] == []


def test_returns_orders_where_client_is_customer(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    make_order(tenant_a, customer=client_fatou)
    make_order(tenant_b, customer=client_fatou)

    items = get(authenticated_client, client_fatou).json()["orders"]

    assert len(items) == 2
    assert {item["tenant_slug"] for item in items} == {tenant_a.slug, tenant_b.slug}


def test_does_not_return_orders_of_other_clients(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    mine = make_order(tenant_a, customer=client_fatou)
    make_order(tenant_a, customer=client_aicha)

    items = get(authenticated_client, client_fatou).json()["orders"]

    assert [item["id"] for item in items] == [str(mine.id)]


def test_does_not_return_orders_without_a_customer(
    authenticated_client, client_fatou, tenant_a,
):
    """Une commande au guichet, sans compte : personne ne la voit dans son espace."""
    make_order(tenant_a, customer=None, customer_name="Fatou Mbaye")

    assert get(authenticated_client, client_fatou).json()["orders"] == []


def test_tenant_filter(authenticated_client, client_fatou, tenant_a, tenant_b):
    make_order(tenant_a, customer=client_fatou)
    make_order(tenant_b, customer=client_fatou)

    items = get(authenticated_client, client_fatou, f"?tenant={tenant_b.slug}").json()["orders"]

    assert len(items) == 1
    assert items[0]["tenant_slug"] == tenant_b.slug


def test_status_filter(authenticated_client, client_fatou, tenant_a):
    make_order(tenant_a, customer=client_fatou, status=Order.Status.CONFIRMED)
    delivered = make_order(tenant_a, customer=client_fatou, status=Order.Status.DELIVERED)

    items = get(authenticated_client, client_fatou, "?status=delivered").json()["orders"]

    assert [item["id"] for item in items] == [str(delivered.id)]


def test_soft_deleted_order_disappears(authenticated_client, client_fatou, tenant_a):
    order = make_order(tenant_a, customer=client_fatou)
    order.soft_delete()

    assert get(authenticated_client, client_fatou).json()["orders"] == []


def test_serializer_excludes_internal_fields(
    authenticated_client, client_fatou, tenant_a, user_admin_a,
):
    make_order(
        tenant_a, customer=client_fatou, created_by=user_admin_a,
        instructions="Appeler le dispatcher avant livraison.",
        metadata={"marge": 4200},
    )

    item = get(authenticated_client, client_fatou).json()["orders"][0]

    for leaked in ("created_by", "metadata", "instructions", "customer", "trip"):
        assert leaked not in item
    assert "dispatcher" not in str(item)
    assert "4200" not in str(item)


def test_exposes_the_expected_fields(authenticated_client, client_fatou, tenant_a):
    make_order(tenant_a, customer=client_fatou)

    item = get(authenticated_client, client_fatou).json()["orders"][0]

    assert set(item) == {
        "id", "tenant_slug", "tenant_name", "internal_id", "pickup_place_name",
        "dropoff_place_name", "status", "payment_status", "total_amount_xof",
        "priority", "created_at",
    }


def test_staff_is_refused(authenticated_client, user_admin_a):
    assert authenticated_client(user_admin_a).get(URL).status_code == 403


def test_anonymous_is_refused(api_client):
    assert api_client.get(URL).status_code == 401
