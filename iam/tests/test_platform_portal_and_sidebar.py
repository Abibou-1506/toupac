"""
TOUPAC IAM — Visibilité des entrées plateforme et documentation du portail.

La sidebar Unfold est déclarative : elle n'applique aucune permission d'elle-même
et afficherait les entrées plateforme à un admin de compagnie, qui récolterait un
403 au clic. Ces tests verrouillent le callback qui ferme ce trou.
"""
import pytest

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.tests.platform_helpers import admin_client
from iam.unfold import is_toupac_superadmin

pytestmark = pytest.mark.django_db

PLATFORM_LINKS = [
    "/admin/iam/platformcredential/",
    "/admin/iam/tenantsubscription/",
    "/admin/iam/platformauditlog/",
]


def test_sidebar_shows_platform_entries_to_superadmin(superadmin):
    body = admin_client(superadmin).get("/admin/").content.decode()

    for link in PLATFORM_LINKS:
        assert link in body, f"{link} absent de la sidebar superadmin"


def test_sidebar_hides_platform_entries_from_tenant_admin(user_admin_a):
    body = admin_client(user_admin_a).get("/admin/").content.decode()

    for link in PLATFORM_LINKS:
        assert link not in body, f"{link} visible par un admin de compagnie"
    # La section reste présente : seules les entrées plateforme disparaissent.
    assert "/admin/iam/apicredential/" in body


def test_permission_callback_rejects_anonymous_and_tenant_admin(superadmin, user_admin_a):
    from django.contrib.auth.models import AnonymousUser

    def request_for(user):
        return type("R", (), {"user": user})()

    assert is_toupac_superadmin(request_for(superadmin)) is True
    assert is_toupac_superadmin(request_for(user_admin_a)) is False
    assert is_toupac_superadmin(request_for(AnonymousUser())) is False
    assert is_toupac_superadmin(type("R", (), {})()) is False


def test_developer_portal_documents_platform_mode(client):
    """La doc plateforme dérive du code : elle ne peut pas annoncer un scope fantôme."""
    body = client.get("/developers/").content.decode()

    assert "tpc_platform_" in body
    assert "X-Tenant-ID" in body
    assert "/api/v1/platform/tenants/" in body
    assert "/api/v1/platform/health/" in body
    for scope in PLATFORM_AVAILABLE_SCOPES:
        assert scope in body, f"scope {scope} absent du portail"
    assert "chatbot-bi" in body


def test_developer_portal_states_the_no_super_scope_doctrine(client):
    body = client.get("/developers/").content.decode()

    assert "platform:*" in body  # cité pour dire qu'il n'existe pas
    assert "platform:voyage:write" not in body
