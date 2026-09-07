"""
TOUPAC IAM — Visibilité des entrées plateforme dans l'administration.

La sidebar Unfold est déclarative : elle n'applique aucune permission d'elle-même
et afficherait les entrées plateforme à un admin de compagnie, qui récolterait un
403 au clic. Ces tests verrouillent le callback qui ferme ce trou.

La documentation, elle, est vérifiée dans `developers/tests/` — elle a son propre
public et ses propres pages depuis USR-4.
"""
import pytest

from iam.tests.platform_helpers import admin_client
from iam.unfold import is_toupac_superadmin

pytestmark = pytest.mark.django_db

PLATFORM_LINKS = [
    "/admin/iam/platformcredential/",
    "/admin/iam/platformauditlog/",
]


def test_sidebar_shows_platform_entries_to_superadmin(superadmin):
    body = admin_client(superadmin).get("/admin/").content.decode()

    for link in PLATFORM_LINKS:
        assert link in body, f"{link} absent de la sidebar superadmin"


def test_sidebar_no_longer_offers_subscriptions(superadmin):
    """Le concept d'abonnement est retiré : le menu ne doit plus y mener (USR-4)."""
    body = admin_client(superadmin).get("/admin/").content.decode()

    assert "/admin/iam/tenantsubscription/" not in body


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
