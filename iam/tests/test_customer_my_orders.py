"""
TOUPAC IAM — `/customer/my-orders/`, les colis où le client est partie prenante.

Deux liens mènent à une commande : `Order.customer` (expéditeur) et
`Order.recipient_user` (destinataire). La vue rend l'union des deux ; chaque
élément porte un champ `role` — « sender », « recipient » ou « both » — qui
dit à l'app CLIENT lequel l'acting user est, pour pouvoir distinguer
visuellement « j'ai envoyé » et « je dois recevoir » sans refetcher.
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
        "role",
    }


# ─── Le destinataire ───
#
# `Order.recipient_user` existe depuis le ticket E1E2 et est renseigné par le
# seed depuis le ticket billing-invoice-customer-type-alignment. La vue l'a
# intégré le 1er oct 2026 : un destinataire voit désormais le colis qu'il
# attend, avec `role` qui dit lequel des deux liens le concerne.


def test_returns_orders_where_client_is_recipient(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """Ousmane envoie à Fatou — Fatou doit voir le colis arriver."""
    sent_to_fatou = make_order(
        tenant_a, customer=client_aicha, recipient_user=client_fatou,
    )

    items = get(authenticated_client, client_fatou).json()["orders"]

    assert [item["id"] for item in items] == [str(sent_to_fatou.id)]
    assert items[0]["role"] == "recipient"


def test_role_sender_when_client_is_the_customer(
    authenticated_client, client_fatou, tenant_a,
):
    make_order(tenant_a, customer=client_fatou)

    assert get(authenticated_client, client_fatou).json()["orders"][0]["role"] == "sender"


def test_role_both_when_client_sends_to_themselves(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Cas rare mais légitime : un client s'expédie un colis à lui-même (envoi
    différé entre deux villes qu'il va rejoindre). L'union SQL rendrait alors
    la même ligne deux fois sans `.distinct()`.
    """
    make_order(tenant_a, customer=client_fatou, recipient_user=client_fatou)

    items = get(authenticated_client, client_fatou).json()["orders"]

    assert len(items) == 1
    assert items[0]["role"] == "both"


def test_mixed_sender_and_recipient_orders_are_both_listed(
    authenticated_client, client_fatou, client_aicha, tenant_a, tenant_b,
):
    """Les deux chemins coexistent dans la même réponse, un rôle par ligne."""
    sent = make_order(tenant_a, customer=client_fatou)
    received = make_order(tenant_b, customer=client_aicha, recipient_user=client_fatou)

    roles_by_id = {
        item["id"]: item["role"]
        for item in get(authenticated_client, client_fatou).json()["orders"]
    }

    assert roles_by_id == {str(sent.id): "sender", str(received.id): "recipient"}


def test_a_tenant_without_any_role_returns_nothing(
    authenticated_client, client_fatou, client_aicha, tenant_a, tenant_b,
):
    """Un tenant où le client n'est ni expéditeur ni destinataire reste muet."""
    make_order(tenant_b, customer=client_aicha, recipient_user=client_aicha)

    items = get(authenticated_client, client_fatou).json()["orders"]

    assert items == []


# ─── Isolation (sécurité) ───

def test_sender_does_not_see_an_order_sent_to_them_by_another_sender(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """
    Ousmane est customer d'une commande dont le destinataire est Fatou. Côté
    Ousmane, la commande apparaît. Côté Fatou, elle apparaît aussi — mais
    uniquement comme destinataire. Le filtre reste une union OR, pas une
    divulgation transverse.
    """
    make_order(tenant_a, customer=client_aicha, recipient_user=client_fatou)

    fatou_items = get(authenticated_client, client_fatou).json()["orders"]
    aicha_items = get(authenticated_client, client_aicha).json()["orders"]

    assert len(fatou_items) == 1 and fatou_items[0]["role"] == "recipient"
    assert len(aicha_items) == 1 and aicha_items[0]["role"] == "sender"


def test_a_third_party_sees_nothing(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """Un client ni expéditeur ni destinataire ne voit rien de la commande."""
    make_order(tenant_a, customer=client_aicha, recipient_user=client_aicha)

    third, _ = User.get_or_create_client(email="moussa@example.sn", first_name="Moussa", last_name="Ba")

    assert get(authenticated_client, third).json()["orders"] == []


def test_staff_is_refused(authenticated_client, user_admin_a):
    assert authenticated_client(user_admin_a).get(URL).status_code == 403


def test_anonymous_is_refused(api_client):
    assert api_client.get(URL).status_code == 401
