"""TOUPAC Developers — Portail public de documentation d'intégration."""
import re

import pytest
from django.test import Client

from iam.scopes import AVAILABLE_SCOPES

PORTAL_URL = "/developers/"

SECTION_ANCHORS = [
    "introduction", "quickstart", "auth", "scopes", "rate-limits",
    "errors", "pagination", "filters", "examples", "swagger", "contact",
]


@pytest.fixture
def portal_html():
    response = Client().get(PORTAL_URL)
    assert response.status_code == 200
    return response.content.decode()


def test_portal_accessible_without_authentication():
    """Un partenaire sans clé doit pouvoir lire la doc — c'est son point d'entrée."""
    assert Client().get(PORTAL_URL).status_code == 200


def test_portal_contains_all_required_sections(portal_html):
    missing = [anchor for anchor in SECTION_ANCHORS if f'id="{anchor}"' not in portal_html]
    assert missing == []


def test_portal_lists_all_scopes_from_available_scopes(portal_html):
    """La doc est générée depuis iam.scopes : elle ne peut pas diverger du code."""
    missing = [name for name in AVAILABLE_SCOPES if name not in portal_html]
    assert missing == []
    assert len(AVAILABLE_SCOPES) == 15


def test_portal_shows_scope_descriptions(portal_html):
    for description in AVAILABLE_SCOPES.values():
        assert description in portal_html


def test_portal_documents_api_key_header_and_rate_limits(portal_html):
    assert "X-API-Key" in portal_html
    assert "1 000" in portal_html
    assert "10 000" in portal_html
    assert "Retry-After" in portal_html


def test_portal_links_to_swagger(portal_html):
    assert 'href="/api/docs/"' in portal_html


#: Suffixe des clés d'exemple. Une clé réellement émise porte 8 hexa après son
#: préfixe : tout identifiant de cette forme qui ne serait pas celui-ci aurait
#: été recopié depuis la production.
FICTITIOUS_KEY_SUFFIXES = {"a1b2c3d4"}


def assert_no_real_credentials(html):
    """Aucun identifiant de clé affiché n'est autre chose qu'un exemple fictif.

    La règle portait à l'origine sur le nombre d'occurrences de `tpc_`, ce qui
    ne valait que tant qu'une seule clé d'exemple figurait sur la page. On
    vérifie désormais ce qu'elle voulait dire — partagé par les deux portails,
    qui montrent chacun leur famille de clé.
    """
    for match in re.finditer(r"tpc_(?:platform_)?([0-9a-f]{8})\b", html):
        assert match.group(1) in FICTITIOUS_KEY_SUFFIXES, (
            f"clé potentiellement réelle : {match.group(0)}"
        )

    # Et jamais de secret : une clé complète s'écrit prefix.secret.
    assert not re.search(r"tpc_(?:platform_)?[0-9a-f]{8}\.[A-Za-z0-9_\-]{20,}", html)


def test_portal_contains_no_real_credentials(portal_html):
    """Les exemples doivent rester des placeholders, jamais une vraie clé."""
    assert "PREFIX.SECRET" in portal_html
    assert "TOUPAC_API_KEY" in portal_html
    assert "tpc_a1b2c3d4" in portal_html  # exemple explicitement fictif

    assert_no_real_credentials(portal_html)
