"""
TOUPAC Developers — Le portail partenaires et sa séparation d'avec le portail tenant.

Deux publics, deux pages. Un intégrateur qui branche l'ERP de sa compagnie et
une équipe partenaire qui sert toutes les compagnies n'ont ni les mêmes clés, ni
les mêmes en-têtes, ni les mêmes quotas — les réunir obligeait chacun à ignorer
la moitié du texte sans savoir laquelle.
"""
import pytest

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.scopes import AVAILABLE_SCOPES

pytestmark = pytest.mark.django_db

PARTNER_URL = "/partners/developers/"
TENANT_URL = "/developers/"


@pytest.fixture
def partner_html(client):
    response = client.get(PARTNER_URL)
    assert response.status_code == 200
    return response.content.decode()


@pytest.fixture
def tenant_html(client):
    response = client.get(TENANT_URL)
    assert response.status_code == 200
    return response.content.decode()


# ─── Portail partenaires ───

def test_partner_portal_is_reachable_without_authentication(partner_html):
    """C'est le point d'entrée d'un partenaire qui n'a pas encore de clé."""
    assert "Mode plateforme" in partner_html


def test_partner_portal_contains_no_real_credentials(partner_html):
    """Même garde que sur le portail tenant : les exemples restent fictifs."""
    from developers.tests.test_portal import assert_no_real_credentials

    assert "tpc_platform_a1b2c3d4" in partner_html  # exemple explicitement fictif
    assert_no_real_credentials(partner_html)


def test_partner_portal_lists_every_platform_scope(partner_html):
    for scope in PLATFORM_AVAILABLE_SCOPES:
        assert scope in partner_html, f"scope {scope} absent du portail partenaires"


def test_partner_portal_scope_table_lists_only_platform_scopes(partner_html):
    """
    Le tableau des scopes ne propose que ceux qui s'appliquent à ces clés.

    Les scopes de compagnie apparaissent bien ailleurs sur la page — le tableau
    comparatif les cite pour opposer les deux modes — mais jamais comme une
    option offerte au partenaire.
    """
    table = partner_html.split('<table class="table table-scopes">', 1)[1]
    table = table.split("</table>", 1)[0]

    for scope in AVAILABLE_SCOPES:
        assert f"<code>{scope}</code>" not in table
    for scope in PLATFORM_AVAILABLE_SCOPES:
        assert f"<code>{scope}</code>" in table


def test_partner_portal_documents_the_acting_user_header(partner_html):
    assert "X-Acting-User-Email" in partner_html
    assert "X-Acting-User-Phone" in partner_html
    assert "X-Tenant-ID" in partner_html


def test_partner_portal_documents_both_throttles(partner_html):
    """Le second plafond surprend s'il n'est pas annoncé."""
    assert "1 000" in partner_html
    assert "200" in partner_html


def test_partner_portal_states_the_new_key_doctrine(partner_html):
    """Durée de vie et restriction d'origine ont changé — la doc doit suivre."""
    assert "jusqu'à sa révocation" in partner_html
    assert "platform:*" in partner_html  # cité pour dire qu'il n'existe pas


def test_partner_portal_no_longer_claims_forced_rotation(partner_html):
    assert "expire au bout de 90 jours" not in partner_html
    assert "la rotation n'est pas optionnelle" not in partner_html


def test_partner_portal_no_longer_mentions_subscriptions(partner_html):
    """Le concept est retiré : plus aucune mention de compagnies « abonnées »."""
    assert "abonnées" not in partner_html
    assert "abonnement" not in partner_html.lower()


# ─── Portail tenant ───

def test_tenant_portal_no_longer_exposes_platform_content(tenant_html):
    """Le mode plateforme a sa propre page : il disparaît de celle-ci."""
    assert "tpc_platform_" not in tenant_html
    assert "X-Acting-User-Email" not in tenant_html
    for scope in PLATFORM_AVAILABLE_SCOPES:
        assert scope not in tenant_html


def test_tenant_portal_still_lists_its_own_scopes(tenant_html):
    for scope in AVAILABLE_SCOPES:
        assert scope in tenant_html


# ─── Renvois croisés ───

def test_tenant_portal_points_to_the_partner_portal(tenant_html):
    assert PARTNER_URL in tenant_html


def test_partner_portal_points_to_the_tenant_portal(partner_html):
    assert f'href="{TENANT_URL}"' in partner_html


def test_each_page_states_who_it_is_for(tenant_html, partner_html):
    """Arriver au mauvais endroit doit se voir en une phrase."""
    assert "intégrations d'une compagnie" in tenant_html
    assert "plusieurs compagnies" in partner_html
