"""
TOUPAC Notifications — Resolvers d'authentification, de commerce et de billets.

Chaque resolver est appelé directement, sans passer par `emit()` : on vérifie
ici la résolution, pas l'émission. `temporary_resolver` n'a rien à faire dans
ces tests — il sert à substituer un resolver, pas à éprouver celui qui est
réellement enregistré.
"""
import uuid

import pytest

from iam.models import User
from iam.tests.customer_factories import make_invoice, make_order, make_reservation
from notifications.resolvers.base import get_resolver

pytestmark = pytest.mark.django_db


def resolve(key, context=None, tenant=None):
    """Appelle le resolver enregistré et rend l'ensemble des comptes visés."""
    resolved = get_resolver(key)(context or {}, tenant)
    return {entry.user.pk for entry in resolved}


# ─── auth ───

def test_auth_self_finds_the_person_whatever_their_role(client_fatou, user_driver_a):
    """
    Aucun filtre de rôle : une connexion par code sert client comme salarié.

    C'est le seul endroit du système où le rôle du destinataire n'est pas connu
    à l'avance.
    """
    assert resolve("auth.self", {"user_id": client_fatou.pk}) == {client_fatou.pk}
    assert resolve("auth.self", {"user_id": user_driver_a.pk}) == {user_driver_a.pk}


def test_auth_self_returns_nothing_for_an_unknown_account():
    assert resolve("auth.self", {"user_id": uuid.uuid4()}) == set()
    assert resolve("auth.self", {}) == set()


def test_auth_self_ignores_a_deactivated_account(client_fatou):
    """Un compte désactivé ne doit plus recevoir de code de connexion."""
    client_fatou.is_active = False
    client_fatou.save(update_fields=["is_active"])

    assert resolve("auth.self", {"user_id": client_fatou.pk}) == set()


def test_auth_self_and_admins_reaches_the_platform_not_the_company(
    client_fatou, platform_superadmin, user_admin_a, tenant_a,
):
    """
    « Admin SI » de la charte est TOUPAC, pas l'administrateur du client.

    Prévenir l'admin d'une compagnie d'une activité suspecte sur le compte d'un
    client lui donnerait une information qu'il n'a pas à connaître.
    """
    found = resolve(
        "auth.self_and_admins", {"user_id": client_fatou.pk}, tenant=tenant_a,
    )

    assert found == {client_fatou.pk, platform_superadmin.pk}
    assert user_admin_a.pk not in found


def test_auth_self_and_admins_still_warns_the_platform_without_the_person(
    platform_superadmin,
):
    """Un identifiant perdu ne doit pas faire taire l'alerte de sécurité."""
    assert resolve("auth.self_and_admins", {}) == {platform_superadmin.pk}


# ─── commerce : commandes ───

def test_order_customer_follows_a_parcel(parcel_order, client_fatou):
    found = resolve(
        "order.customer", {"order_type": "parcel", "order_id": parcel_order.pk},
    )

    assert found == {client_fatou.pk}


def test_order_customer_follows_a_reservation(tenant_a, client_fatou):
    reservation = make_reservation(tenant_a, customer_user=client_fatou)

    found = resolve(
        "order.customer",
        {"order_type": "reservation", "order_id": reservation.pk},
    )

    assert found == {client_fatou.pk}


def test_an_unknown_order_type_resolves_to_nobody(parcel_order):
    """Un type qui ne se devine pas doit rendre vide, pas choisir au hasard."""
    assert resolve(
        "order.customer", {"order_type": "abonnement", "order_id": parcel_order.pk},
    ) == set()


def test_a_missing_order_resolves_to_nobody():
    assert resolve(
        "order.customer", {"order_type": "parcel", "order_id": uuid.uuid4()},
    ) == set()


def test_a_soft_deleted_order_resolves_to_nobody(parcel_order):
    """Une commande effacée au titre du RGPD ne notifie plus personne."""
    from django.utils import timezone

    parcel_order.deleted_at = timezone.now()
    parcel_order.save(update_fields=["deleted_at"])

    assert resolve(
        "order.customer", {"order_type": "parcel", "order_id": parcel_order.pk},
    ) == set()


def test_order_customer_and_agent_adds_the_counter_staff(
    parcel_order, client_fatou, user_agent_a, tenant_a,
):
    found = resolve(
        "order.customer_and_agent",
        {"order_type": "parcel", "order_id": parcel_order.pk},
        tenant=tenant_a,
    )

    assert found == {client_fatou.pk, user_agent_a.pk}


def test_order_customer_and_agent_never_crosses_companies(
    parcel_order, tenant_a, tenant_b,
):
    """Un agent d'une autre compagnie n'a rien à voir avec cette commande."""
    from conftest import PASSWORD

    other = User.objects.create_user(
        email="agent.b@toupac.sn", password=PASSWORD, first_name="Awa",
        last_name="Ndiaye", tenant=tenant_b, role=User.Role.AGENT,
    )

    found = resolve(
        "order.customer_and_agent",
        {"order_type": "parcel", "order_id": parcel_order.pk},
        tenant=tenant_a,
    )

    assert other.pk not in found


# ─── commerce : paiements ───

def test_payment_customer_follows_the_order(payment_on_order, client_fatou):
    assert resolve("payment.customer", {"payment_id": payment_on_order.pk}) == {
        client_fatou.pk,
    }


def test_payment_customer_follows_the_reservation(tenant_a, client_aicha):
    """
    Troisième chemin, que le ticket ne mentionnait pas.

    `Payment` se relie à une commande, à une réservation **ou** à une facture ;
    ignorer la réservation aurait laissé les paiements de billets sans
    destinataire.
    """
    from billing.models import Payment

    reservation = make_reservation(tenant_a, customer_user=client_aicha)
    payment = Payment.objects.create(
        tenant=tenant_a, reservation=reservation, provider=Payment.Provider.WAVE,
        amount_xof=15000, status=Payment.Status.SUCCESS,
    )

    assert resolve("payment.customer", {"payment_id": payment.pk}) == {client_aicha.pk}


def test_payment_customer_follows_an_invoice_of_a_toupac_client(tenant_a, client_fatou):
    from billing.models import Payment

    invoice = make_invoice(tenant_a, customer_id=client_fatou.pk)
    payment = Payment.objects.create(
        tenant=tenant_a, invoice=invoice, provider=Payment.Provider.CASH,
        amount_xof=15000, status=Payment.Status.SUCCESS,
    )

    assert resolve("payment.customer", {"payment_id": payment.pk}) == {client_fatou.pk}


def test_an_external_invoice_customer_is_never_mistaken_for_an_account(
    tenant_a, client_fatou,
):
    """
    `customer_id` est polymorphe : le lire sans vérifier `customer_type`
    enverrait la facture d'un client externe au compte TOUPAC dont
    l'identifiant coïnciderait.
    """
    from billing.models import CUSTOMER_TYPE_EXTERNAL, Payment

    invoice = make_invoice(
        tenant_a, customer_id=client_fatou.pk, customer_type=CUSTOMER_TYPE_EXTERNAL,
    )
    payment = Payment.objects.create(
        tenant=tenant_a, invoice=invoice, provider=Payment.Provider.CASH,
        amount_xof=15000, status=Payment.Status.SUCCESS,
    )

    assert resolve("payment.customer", {"payment_id": payment.pk}) == set()


def test_a_payment_attached_to_nothing_resolves_to_nobody(tenant_a):
    from billing.models import Payment

    payment = Payment.objects.create(
        tenant=tenant_a, provider=Payment.Provider.CASH,
        amount_xof=15000, status=Payment.Status.SUCCESS,
    )

    assert resolve("payment.customer", {"payment_id": payment.pk}) == set()


def test_a_missing_payment_resolves_to_nobody():
    assert resolve("payment.customer", {"payment_id": uuid.uuid4()}) == set()


def test_payment_customer_and_finance_adds_the_company_admin(
    payment_on_order, client_fatou, user_admin_a, tenant_a,
):
    found = resolve(
        "payment.customer_and_finance",
        {"payment_id": payment_on_order.pk}, tenant=tenant_a,
    )

    assert found == {client_fatou.pk, user_admin_a.pk}


# ─── commerce : billets ───

def test_ticket_customer_finds_the_traveller(tenant_a, client_fatou):
    reservation = make_reservation(tenant_a, customer_user=client_fatou)

    assert resolve("ticket.customer", {"reservation_id": reservation.pk}) == {
        client_fatou.pk,
    }


def test_a_counter_sale_without_an_account_resolves_to_nobody(tenant_a):
    """
    Un billet vendu au guichet à quelqu'un sans compte n'a pas de destinataire.

    Rendre vide est la bonne réponse — fabriquer un destinataire serait pire.
    """
    reservation = make_reservation(tenant_a, customer_user=None)

    assert resolve("ticket.customer", {"reservation_id": reservation.pk}) == set()


def test_a_missing_reservation_resolves_to_nobody():
    assert resolve("ticket.customer", {"reservation_id": uuid.uuid4()}) == set()
    assert resolve("ticket.customer", {}) == set()


# ─── La famille CLIENT dans son ensemble ───

CLIENT_RESOLVERS = [
    ("order.customer", "order_id"),
    ("order.customer_and_agent", "order_id"),
    ("ticket.customer", "reservation_id"),
]


def test_client_resolvers_find_a_tenantless_client(tenant_a, client_fatou):
    """
    Le mode de défaillance le plus probable de tout ce ticket.

    Un client est global : `tenant=None`. Un resolver qui le chercherait par
    `tenant=tenant`, par mimétisme avec les resolvers de personnel, rendrait
    une liste vide — et l'émission passerait pour un « personne à prévenir »
    légitime, sans une ligne en base pour dire que c'était une erreur.
    """
    assert client_fatou.tenant_id is None

    order = make_order(tenant_a, customer=client_fatou)
    reservation = make_reservation(tenant_a, customer_user=client_fatou)

    assert resolve(
        "order.customer", {"order_type": "parcel", "order_id": order.pk},
        tenant=tenant_a,
    ) == {client_fatou.pk}
    assert resolve(
        "ticket.customer", {"reservation_id": reservation.pk}, tenant=tenant_a,
    ) == {client_fatou.pk}
