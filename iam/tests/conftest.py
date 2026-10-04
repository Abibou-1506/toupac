"""Fixtures partagées par les tests iam.

Ici plutôt que dans `platform_helpers` : une fixture importée dans un module de
test masque le paramètre du même nom (F811 côté ruff, et pytest résout la
fixture par son nom, pas par l'import). Un conftest de package les expose sans
import, ce qui est la manière idiomatique.

Le conftest racine reste réservé aux fixtures transverses à tous les modules.
"""
import pytest

from iam.models import User


@pytest.fixture
def superadmin():
    """Personnel TOUPAC interne : sans tenant, accès transverse."""
    return User.objects.create_user(
        email="super@toupac.sn", password="TestPass#2026", first_name="Super",
        last_name="Admin", tenant=None, role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True,
    )


# ─── Variantes `is_staff=True` pour les tests admin (Ticket 4 Gamma) ───
#
# Les fixtures `user_dispatcher_a` / `user_agent_a` / `user_controller_a` du
# conftest racine ont `is_staff=False` par défaut (helper _make_user restreint
# is_staff=True à ADMIN). Pour tester les restrictions par rôle sur /admin/
# (403 vs login redirect), on a besoin de ces mêmes rôles avec is_staff=True.
# Fixtures séparées plutôt qu'un override — préserve les tests existants qui
# dépendent de l'is_staff=False des fixtures racines.

@pytest.fixture
def user_dispatcher_staff_a(tenant_a):
    """DISPATCHER tenant_a avec is_staff=True. Pour tester /admin/ 403."""
    return User.objects.create_user(
        email="dispatcher.staff.a@toupac.sn", password="TestPass#2026",
        first_name="Dispatch", last_name="Staff", tenant=tenant_a,
        role=User.Role.DISPATCHER, is_staff=True,
    )


@pytest.fixture
def user_agent_staff_a(tenant_a):
    """AGENT tenant_a avec is_staff=True. Pour tester /admin/ 403."""
    return User.objects.create_user(
        email="agent.staff.a@toupac.sn", password="TestPass#2026",
        first_name="Agent", last_name="Staff", tenant=tenant_a,
        role=User.Role.AGENT, is_staff=True,
    )


@pytest.fixture
def user_controller_staff_a(tenant_a):
    """CONTROLLER tenant_a avec is_staff=True. Pour tester /admin/ 403."""
    return User.objects.create_user(
        email="controller.staff.a@toupac.sn", password="TestPass#2026",
        first_name="Controller", last_name="Staff", tenant=tenant_a,
        role=User.Role.CONTROLLER, is_staff=True,
    )


@pytest.fixture
def client_fatou():
    """Client TOUPAC : global, sans compagnie, sans mot de passe utilisable."""
    user, _ = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
        first_name="Fatou", last_name="Mbaye",
    )
    return user
