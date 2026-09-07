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


def test_portal_contains_no_real_credentials(portal_html):
    """Les exemples doivent rester des placeholders, jamais une vraie clé.

    La règle portait auparavant sur le nombre d'occurrences de `tpc_`, ce qui
    valait tant que la page ne montrait qu'une clé d'exemple. La section
    plateforme en a ajouté d'autres (un exemple `tpc_platform_`, et des mentions
    des deux préfixes dans le tableau comparatif) : on vérifie donc directement
    ce que la règle voulait dire, à savoir qu'aucun identifiant de clé affiché
    n'est autre chose qu'un exemple fictif connu.
    """
    assert "PREFIX.SECRET" in portal_html
    assert "TOUPAC_API_KEY" in portal_html
    # Exemples explicitement fictifs, un par famille de clé.
    assert "tpc_a1b2c3d4" in portal_html
    assert "tpc_platform_a1b2c3d4" in portal_html

    # Une clé réellement émise porte 8 hexa après son préfixe. Tout identifiant
    # de cette forme qui ne serait pas l'un des exceptions ci-dessus serait une
    # vraie clé recopiée dans la documentation.
    fictitious = {"a1b2c3d4"}
    for match in re.finditer(r"tpc_(?:platform_)?([0-9a-f]{8})\b", portal_html):
        assert match.group(1) in fictitious, f"clé potentiellement réelle : {match.group(0)}"

    # Et jamais de secret : une clé complète s'écrit prefix.secret.
    assert not re.search(r"tpc_(?:platform_)?[0-9a-f]{8}\.[A-Za-z0-9_\-]{20,}", portal_html)
