"""TOUPAC Developers — Portail partenaire plateforme.

Depuis le pivot du 4 oct 2026 (TOUPAC entité unique), un seul portail subsiste
à `/partners/developers/`. L'ancien portail tenant (`/developers/`) et ses tests
ont été supprimés — ce public n'existe plus.
"""
import re

import pytest

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.scopes import AVAILABLE_SCOPES

pytestmark = pytest.mark.django_db

PARTNER_URL = "/partners/developers/"


@pytest.fixture
def partner_html(client):
    response = client.get(PARTNER_URL)
    assert response.status_code == 200
    return response.content.decode()


#: Suffixe des clés d'exemple. Une clé réellement émise porte 8 hexa après son
#: préfixe : tout identifiant de cette forme qui ne serait pas celui-ci aurait
#: été recopié depuis la production.
FICTITIOUS_KEY_SUFFIXES = {"a1b2c3d4"}


def assert_no_real_credentials(html):
    """Aucun identifiant de clé affiché n'est autre chose qu'un exemple fictif."""
    for match in re.finditer(r"tpc_(?:platform_)?([0-9a-f]{8})\b", html):
        assert match.group(1) in FICTITIOUS_KEY_SUFFIXES, (
            f"clé potentiellement réelle : {match.group(0)}"
        )
    # Et jamais de secret : une clé complète s'écrit prefix.secret.
    assert not re.search(r"tpc_(?:platform_)?[0-9a-f]{8}\.[A-Za-z0-9_\-]{20,}", html)


# ─── Portail partenaires ───

def test_partner_portal_is_reachable_without_authentication(partner_html):
    """C'est le point d'entrée d'un partenaire qui n'a pas encore de clé."""
    assert "Mode plateforme" in partner_html


def test_partner_portal_contains_no_real_credentials(partner_html):
    """Les exemples restent fictifs."""
    assert "tpc_platform_a1b2c3d4" in partner_html  # exemple explicitement fictif
    assert_no_real_credentials(partner_html)


def test_partner_portal_lists_every_platform_scope(partner_html):
    for scope in PLATFORM_AVAILABLE_SCOPES:
        assert scope in partner_html, f"scope {scope} absent du portail partenaires"


def test_partner_portal_scope_table_lists_only_platform_scopes(partner_html):
    """
    Le tableau des scopes ne propose que ceux qui s'appliquent à ces clés.

    Les scopes tenant (voyage:read…) ne doivent pas y figurer : ils sont réservés
    au staff TOUPAC interne et ne sont pas distribués aux partenaires.
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
    """Durée de vie et restriction d'origine : la doc reste à jour."""
    assert "jusqu'à sa révocation" in partner_html
    assert "platform:*" in partner_html  # cité pour dire qu'il n'existe pas


def test_partner_portal_no_longer_claims_forced_rotation(partner_html):
    assert "expire au bout de 90 jours" not in partner_html
    assert "la rotation n'est pas optionnelle" not in partner_html


def test_partner_portal_no_longer_mentions_subscriptions(partner_html):
    """Le concept est retiré : plus aucune mention de compagnies « abonnées »."""
    assert "abonnées" not in partner_html
    assert "abonnement" not in partner_html.lower()


# ─── Pivot TOUPAC entité unique (4 oct 2026) ───

def test_partner_portal_reflects_toupac_as_single_tenant(partner_html):
    """TOUPAC est présenté comme l'entité d'intégration — pas « multi-compagnies ».

    Détecte toute régression où l'ancien discours multi-tenant externe
    (sahel-express, « plusieurs compagnies », « votre compagnie »…) reviendrait
    par mégarde (merge conflict, revert partiel).
    """
    # Mentions attendues du nouveau modèle.
    assert "toupac" in partner_html.lower()
    # L'exemple d'en-tête utilise bien toupac.
    assert 'X-Tenant-ID: toupac' in partner_html

    # Mentions interdites de l'ancien modèle multi-tenant externe.
    forbidden = [
        "sahel-express",          # exemple de slug multi-tenant obsolète
        "plusieurs compagnies",
        "votre compagnie",
        "toutes les compagnies",
    ]
    for phrase in forbidden:
        assert phrase not in partner_html, (
            f"Mention obsolète « {phrase} » détectée — pivot TOUPAC-seul incomplet."
        )


def test_tenant_portal_url_is_gone():
    """L'ancien portail tenant /developers/ n'existe plus."""
    from django.test import Client
    response = Client().get("/developers/")
    assert response.status_code == 404
