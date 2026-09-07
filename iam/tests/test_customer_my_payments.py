"""
TOUPAC IAM — `/customer/my-payments/`, ce que le client a réglé.

`Payment` ne porte aucun lien direct vers un payeur : on l'atteint par la
commande dont le client est commanditaire, ou par la facture qui le désigne.
Deux points sont critiques et testés comme tels :

- la facture n'est retenue que si `customer_type` vaut `client_user` — sans ce
  filtre, l'identifiant d'un client externe qui coïnciderait avec celui d'un
  compte TOUPAC ouvrirait la facture d'un tiers ;
- être passager ne suffit pas — un billet réglé par un proche appartient à ses
  voyages, pas à ses paiements.
"""
import pytest

from billing.models import CUSTOMER_TYPE_EXTERNAL
from iam.models import User
from iam.tests.customer_factories import (
    make_invoice,
    make_order,
    make_payment,
    make_reservation,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/customer/my-payments/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def get(authenticated_client, user, query=""):
    return authenticated_client(user).get(f"{URL}{query}")


def test_returns_empty_when_no_payments(authenticated_client, client_fatou):
    response = get(authenticated_client, client_fatou)

    assert response.status_code == 200
    assert response.json()["payments"] == []


def test_returns_payment_via_order_customer(authenticated_client, client_fatou, tenant_a):
    order = make_order(tenant_a, customer=client_fatou)
    payment = make_payment(tenant_a, order=order)

    items = get(authenticated_client, client_fatou).json()["payments"]

    assert [item["id"] for item in items] == [str(payment.id)]
    assert items[0]["context_type"] == "order"
    assert items[0]["context_reference"] == order.internal_id


def test_returns_payment_via_invoice_customer_id(authenticated_client, client_fatou, tenant_a):
    invoice = make_invoice(tenant_a, customer_id=client_fatou.id)
    payment = make_payment(tenant_a, invoice=invoice)

    items = get(authenticated_client, client_fatou).json()["payments"]

    assert [item["id"] for item in items] == [str(payment.id)]
    assert items[0]["context_type"] == "invoice"
    assert items[0]["context_reference"] == invoice.invoice_number


def test_ignores_invoice_when_customer_type_is_not_client_user(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Le type doit correspondre, pas seulement l'identifiant.

    `customer_id` est une référence polymorphe : le même UUID peut désigner un
    client externe. Sans le filtre sur `customer_type`, la facture d'un tiers
    remonterait dans l'espace du client.
    """
    invoice = make_invoice(
        tenant_a, customer_id=client_fatou.id, customer_type=CUSTOMER_TYPE_EXTERNAL,
    )
    make_payment(tenant_a, invoice=invoice)

    assert get(authenticated_client, client_fatou).json()["payments"] == []


def test_ignores_invoice_with_blank_customer_type(
    authenticated_client, client_fatou, tenant_a,
):
    """Factures antérieures à la convention : type vide, donc écartées."""
    invoice = make_invoice(tenant_a, customer_id=client_fatou.id, customer_type="")
    make_payment(tenant_a, invoice=invoice)

    assert get(authenticated_client, client_fatou).json()["payments"] == []


def test_does_not_return_payment_of_reservation_paid_by_other(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Fatou voyage, son proche paie.

    Le billet est dans ses voyages ; le paiement appartient à celui qui l'a
    réglé. Aucun croisement entre les deux rôles.
    """
    reservation = make_reservation(tenant_a, customer_user=client_fatou)
    make_payment(tenant_a, reservation=reservation)

    assert get(authenticated_client, client_fatou).json()["payments"] == []


def test_isolation_between_clients(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    mine = make_payment(tenant_a, order=make_order(tenant_a, customer=client_fatou))
    make_payment(tenant_a, order=make_order(tenant_a, customer=client_aicha))

    items = get(authenticated_client, client_fatou).json()["payments"]

    assert [item["id"] for item in items] == [str(mine.id)]


def test_returns_payments_cross_tenant(authenticated_client, client_fatou, tenant_a, tenant_b):
    make_payment(tenant_a, order=make_order(tenant_a, customer=client_fatou))
    make_payment(tenant_b, invoice=make_invoice(tenant_b, customer_id=client_fatou.id))

    items = get(authenticated_client, client_fatou).json()["payments"]

    assert len(items) == 2
    assert {item["tenant_slug"] for item in items} == {tenant_a.slug, tenant_b.slug}


def test_a_payment_matching_both_paths_appears_once(
    authenticated_client, client_fatou, tenant_a,
):
    """Une commande facturée au même client satisfait les deux branches."""
    payment = make_payment(
        tenant_a,
        order=make_order(tenant_a, customer=client_fatou),
        invoice=make_invoice(tenant_a, customer_id=client_fatou.id),
    )

    items = get(authenticated_client, client_fatou).json()["payments"]

    assert [item["id"] for item in items] == [str(payment.id)]


def test_serializer_excludes_provider_internals(authenticated_client, client_fatou, tenant_a):
    make_payment(
        tenant_a, order=make_order(tenant_a, customer=client_fatou),
        provider_tx_id="TX-SECRET-123",
        provider_response={"raw": "charge utile prestataire"},
        failure_reason="timeout gateway",
    )

    item = get(authenticated_client, client_fatou).json()["payments"][0]

    for leaked in ("provider_tx_id", "provider_response", "failure_reason"):
        assert leaked not in item
    assert "TX-SECRET-123" not in str(item)
    assert "charge utile" not in str(item)


def test_exposes_the_expected_fields(authenticated_client, client_fatou, tenant_a):
    make_payment(tenant_a, order=make_order(tenant_a, customer=client_fatou))

    item = get(authenticated_client, client_fatou).json()["payments"][0]

    assert set(item) == {
        "id", "tenant_slug", "tenant_name", "provider", "amount_xof", "status",
        "initiated_at", "completed_at", "context_type", "context_reference",
    }


def test_staff_is_refused(authenticated_client, user_admin_a):
    assert authenticated_client(user_admin_a).get(URL).status_code == 403


def test_anonymous_is_refused(api_client):
    assert api_client.get(URL).status_code == 401
