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


@pytest.fixture
def client_fatou():
    """Client TOUPAC : global, sans compagnie, sans mot de passe utilisable."""
    user, _ = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
        first_name="Fatou", last_name="Mbaye",
    )
    return user
