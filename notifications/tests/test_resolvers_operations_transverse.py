"""
TOUPAC Notifications — Resolvers d'exploitation et transverses.

Famille où le repli de rôles est le plus dense : la charte nomme responsable
flotte, mécanicien, magasinier, IT, finance, direction et responsable gare, que
`User.Role` ne connaît pas. Ces tests fixent ce sur quoi chacun a été replié —
c'est ce qui permettra, le jour où des rôles fins existeront, de voir d'un coup
d'œil ce qu'il faut redécouper.
"""
import uuid

import pytest

from iam.models import User
from iam.tests.customer_factories import make_order, make_reservation
from notifications.resolvers.base import get_resolver

pytestmark = pytest.mark.django_db


def resolve(key, context=None, tenant=None):
    return get_resolver(key)(context or {}, tenant)


def pks(resolved):
    return {entry.user.pk for entry in resolved}


#: Resolvers de pure diffusion à un rôle, et le personnel qu'ils doivent
#: atteindre après repli. Le tableau vaut documentation : il dit d'un coup d'œil
#: qui reçoit quoi aujourd'hui.
BROADCAST_RESOLVERS = {
    "incident.dispatchers_and_admin": {"user_dispatcher_a", "user_admin_a"},
    "gps.dispatchers_and_fleet": {"user_dispatcher_a", "user_admin_a"},
    "gps.dispatchers_and_it": {"user_dispatcher_a", "user_admin_a"},
    "fleet.manager_and_mechanic": {"user_admin_a"},
    "finance.finance_and_station": {"user_admin_a", "user_agent_a"},
    "stock.warehouse_and_purchase": {"user_admin_a"},
    "bi.direction_and_finance": {"user_admin_a"},
}


@pytest.mark.parametrize(("key", "expected"), BROADCAST_RESOLVERS.items())
def test_each_broadcast_resolver_reaches_its_folded_roles(
    request, key, expected, tenant_a, user_dispatcher_a, user_admin_a,
    user_agent_a, user_controller_a,
):
    """
    Le contrôleur est présent dans le décor et ne doit apparaître nulle part :
    sans lui, un resolver trop large passerait inaperçu.
    """
    found = pks(resolve(key, {}, tenant=tenant_a))

    assert found == {request.getfixturevalue(name).pk for name in expected}
    assert user_controller_a.pk not in found


@pytest.mark.parametrize("key", list(BROADCAST_RESOLVERS))
def test_each_broadcast_resolver_is_isolated_by_company(
    key, tenant_a, tenant_b, user_dispatcher_b,
):
    """Aucune diffusion ne doit franchir la frontière d'une compagnie."""
    assert resolve(key, {}, tenant=tenant_a) == []


@pytest.mark.parametrize("key", list(BROADCAST_RESOLVERS))
def test_each_broadcast_resolver_tolerates_an_empty_population(key, tenant_a):
    """Une compagnie sans le rôle visé rend une liste vide, elle ne lève pas."""
    assert resolve(key, {}, tenant=tenant_a) == []


@pytest.mark.parametrize("key", list(BROADCAST_RESOLVERS))
def test_no_broadcast_resolver_ever_reaches_a_client(key, tenant_a, client_fatou):
    """
    Ces événements sont internes à l'exploitation.

    Un client qui recevrait « véhicule hors ligne » ou « stock bas » verrait
    l'intérieur d'une compagnie qui ne le regarde pas.
    """
    assert client_fatou.pk not in pks(resolve(key, {}, tenant=tenant_a))


# ─── Incidents ───

def test_incident_reporter_and_impacted_gathers_two_populations(
    user_dispatcher_a, client_fatou, tenant_a,
):
    """
    Le déclarant est du personnel, l'impacté est un client global.

    Deux populations, deux filtres : c'est le resolver où les confondre serait
    le plus facile.
    """
    found = pks(resolve(
        "incident.reporter_and_impacted",
        {"reporter_user_id": user_dispatcher_a.pk, "impacted_user_id": client_fatou.pk},
        tenant=tenant_a,
    ))

    assert found == {user_dispatcher_a.pk, client_fatou.pk}


def test_an_incident_without_an_identified_client_still_reaches_the_reporter(
    user_dispatcher_a, tenant_a,
):
    """`impacted_user_id` est facultatif — tout incident n'affecte pas un client."""
    found = pks(resolve(
        "incident.reporter_and_impacted",
        {"reporter_user_id": user_dispatcher_a.pk}, tenant=tenant_a,
    ))

    assert found == {user_dispatcher_a.pk}


def test_a_staff_identifier_passed_as_the_impacted_client_is_refused(
    user_dispatcher_a, user_agent_a, tenant_a,
):
    """
    `client_by_id` filtre sur le rôle, et ce n'est pas de la paranoïa.

    Sans ce filtre, un identifiant de salarié glissé dans le mauvais champ lui
    enverrait une notification destinée à un client.
    """
    found = pks(resolve(
        "incident.reporter_and_impacted",
        {"reporter_user_id": user_dispatcher_a.pk, "impacted_user_id": user_agent_a.pk},
        tenant=tenant_a,
    ))

    assert found == {user_dispatcher_a.pk}


# ─── Conformité ───

def test_compliance_gathers_the_admin_and_the_named_driver(
    user_admin_a, user_driver_a, tenant_a,
):
    found = pks(resolve(
        "compliance.responsible_and_driver",
        {"driver_user_id": user_driver_a.pk}, tenant=tenant_a,
    ))

    assert found == {user_admin_a.pk, user_driver_a.pk}


def test_a_document_without_an_assigned_driver_still_reaches_the_admin(
    user_admin_a, tenant_a,
):
    """Un document réglementaire peut porter sur un véhicule sans chauffeur."""
    found = pks(resolve("compliance.responsible_and_driver", {}, tenant=tenant_a))

    assert found == {user_admin_a.pk}


# ─── Approbations ───

def test_approval_reaches_the_named_approver(user_dispatcher_a, user_admin_a, tenant_a):
    found = pks(resolve(
        "approval.approver",
        {"approver_user_id": user_dispatcher_a.pk}, tenant=tenant_a,
    ))

    assert found == {user_dispatcher_a.pk}


def test_approval_falls_back_to_the_administration(user_admin_a, tenant_a):
    """
    Une demande d'approbation qui ne toucherait personne resterait en attente
    indéfiniment — pire qu'un destinataire approximatif.
    """
    assert pks(resolve("approval.approver", {}, tenant=tenant_a)) == {user_admin_a.pk}


def test_an_approver_from_another_company_falls_back_too(
    user_dispatcher_b, user_admin_a, tenant_a,
):
    found = pks(resolve(
        "approval.approver",
        {"approver_user_id": user_dispatcher_b.pk}, tenant=tenant_a,
    ))

    assert found == {user_admin_a.pk}


# ─── Réclamations ───

def test_crm_gathers_the_client_and_the_agents(client_fatou, user_agent_a, tenant_a):
    found = pks(resolve(
        "crm.customer_and_agent",
        {"customer_user_id": client_fatou.pk}, tenant=tenant_a,
    ))

    assert found == {client_fatou.pk, user_agent_a.pk}


def test_crm_finds_a_tenantless_client(client_fatou, tenant_a):
    """Le client est global : le chercher par compagnie ne rendrait jamais rien."""
    assert client_fatou.tenant_id is None

    assert client_fatou.pk in pks(resolve(
        "crm.customer_and_agent",
        {"customer_user_id": client_fatou.pk}, tenant=tenant_a,
    ))


# ─── Campagnes ───

def test_marketing_reaches_the_customers_of_this_company_only(
    tenant_a, tenant_b, client_fatou, client_aicha,
):
    """
    Une compagnie n'a aucun titre à toucher les clients d'une autre.

    Le client est global : sans le lien métier, la « base clients » d'un tenant
    serait celle de la plateforme entière.
    """
    make_reservation(tenant_a, customer_user=client_fatou)
    make_reservation(tenant_b, customer_user=client_aicha)

    assert pks(resolve("marketing.consented_customers", {}, tenant=tenant_a)) == {
        client_fatou.pk,
    }


def test_marketing_gathers_travellers_and_senders(tenant_a, client_fatou, client_aicha):
    make_reservation(tenant_a, customer_user=client_fatou)
    make_order(tenant_a, customer=client_aicha)

    assert pks(resolve("marketing.consented_customers", {}, tenant=tenant_a)) == {
        client_fatou.pk, client_aicha.pk,
    }


def test_a_customer_who_both_travelled_and_shipped_is_resolved_once(
    tenant_a, client_fatou,
):
    """Sans `.distinct()`, la jointure sur deux relations le rendrait deux fois."""
    make_reservation(tenant_a, customer_user=client_fatou)
    make_order(tenant_a, customer=client_fatou)

    resolved = resolve("marketing.consented_customers", {}, tenant=tenant_a)

    assert len(resolved) == 1


def test_marketing_does_not_filter_out_an_opted_out_customer(tenant_a, client_fatou):
    """
    Malgré son nom, ce resolver ne lit pas les préférences.

    L'opt-out de la catégorie `marketing` est appliqué en aval par le service.
    Le dupliquer ici créerait deux endroits à tenir pour une même règle, qui
    divergeraient au premier changement — ce test verrouille le partage.
    """
    client_fatou.notification_preferences = {"marketing": False}
    client_fatou.save(update_fields=["notification_preferences"])
    make_reservation(tenant_a, customer_user=client_fatou)

    assert pks(resolve("marketing.consented_customers", {}, tenant=tenant_a)) == {
        client_fatou.pk,
    }


def test_marketing_never_reaches_staff(tenant_a, user_agent_a, client_fatou):
    make_reservation(tenant_a, customer_user=client_fatou)

    assert user_agent_a.pk not in pks(
        resolve("marketing.consented_customers", {}, tenant=tenant_a),
    )


def test_marketing_without_a_company_resolves_to_nobody(client_fatou, tenant_a):
    make_reservation(tenant_a, customer_user=client_fatou)

    assert resolve("marketing.consented_customers", {}, tenant=None) == []


# ─── Plateforme ───

def test_si_reaches_the_platform_admins_not_the_company_ones(
    platform_superadmin, user_admin_a, tenant_a,
):
    """
    Un incident de plateforme relève de son exploitant.

    Prévenir l'administrateur d'un client d'une panne interne lui donnerait une
    information qu'il ne peut pas exploiter.
    """
    found = pks(resolve("si.admins_and_support", {}, tenant=tenant_a))

    assert found == {platform_superadmin.pk}
    assert user_admin_a.pk not in found


def test_si_resolves_without_a_company(platform_superadmin):
    """Les superadmins sont sans compagnie : `tenant` ne les concerne pas."""
    assert pks(resolve("si.admins_and_support", {}, tenant=None)) == {
        platform_superadmin.pk,
    }


# ─── Entités absentes ───

@pytest.mark.parametrize(("key", "field"), [
    ("incident.reporter_and_impacted", "reporter_user_id"),
    ("compliance.responsible_and_driver", "driver_user_id"),
    ("approval.approver", "approver_user_id"),
    ("crm.customer_and_agent", "customer_user_id"),
])
def test_an_unknown_identifier_never_raises(key, field, tenant_a):
    """Un identifiant qui ne désigne personne rend vide — le contrat d'examples.py."""
    resolve(key, {field: uuid.uuid4()}, tenant=tenant_a)


def test_the_helper_never_hands_back_an_inactive_platform_admin(platform_superadmin):
    platform_superadmin.is_active = False
    platform_superadmin.save(update_fields=["is_active"])

    assert resolve("si.admins_and_support", {}) == []


def test_broadcast_recipients_carry_the_role_scope(user_admin_a, tenant_a):
    """
    Le scope distingue une diffusion d'un envoi nominatif — il est lu par
    `Notification.trigger_scope`, que le centre d'alertes conserve.
    """
    resolved = resolve("bi.direction_and_finance", {}, tenant=tenant_a)

    assert resolved[0].trigger_scope == "role"
    assert resolved[0].trigger_role == User.Role.ADMIN
