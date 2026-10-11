"""Tests du champ `is_superuser` dans la payload /api/v1/auth/me/.

Résout dette V1.1 Vague 4 : le front DriverDetailPage conditionne
l'affichage du DELETE sur les notes RH au statut superuser. Sans le
flag dans la payload, le bouton était grisé pour tous.

Ajout additif, read-only — pas de régression côté app mobile RN.
"""
import pytest

from iam.models import User

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/auth/me/"


def test_auth_me_includes_is_superuser_false_for_regular_user(
    authenticated_client, user_admin_a
):
    """Un admin de compagnie n'est pas superuser TOUPAC."""
    response = authenticated_client(user_admin_a).get(ME_URL)

    assert response.status_code == 200, response.data
    assert "is_superuser" in response.data
    assert response.data["is_superuser"] is False


def test_auth_me_includes_is_superuser_true_for_superuser(
    authenticated_client, platform_superadmin
):
    """Le superadmin TOUPAC a `is_superuser=True` — le front peut
    conditionner les actions réservées (ex. DELETE note RH)."""
    response = authenticated_client(platform_superadmin).get(ME_URL)

    assert response.status_code == 200, response.data
    assert response.data["is_superuser"] is True


def test_auth_me_payload_unchanged_for_other_fields(
    authenticated_client, user_admin_a
):
    """L'ajout de `is_superuser` ne retire aucun champ existant du contrat.

    Régression : l'app RN consomme déjà id/email/first_name/last_name/
    role/tenant_id/tenant_name/phone/is_active. Un champ en moins
    casserait l'écran de profil.
    """
    response = authenticated_client(user_admin_a).get(ME_URL)

    assert response.status_code == 200, response.data
    expected_keys = {
        "id", "email", "first_name", "last_name", "phone", "role",
        "tenant_id", "tenant_name", "is_active", "is_superuser",
    }
    assert expected_keys <= set(response.data.keys()), (
        f"Keys manquantes : {expected_keys - set(response.data.keys())}"
    )
    assert response.data["email"] == user_admin_a.email
    assert response.data["role"] == User.Role.ADMIN
    assert response.data["tenant_id"] == user_admin_a.tenant_id
