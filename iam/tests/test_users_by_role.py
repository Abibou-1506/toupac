"""Tests du picker users par rôle — GET /api/v1/iam/users/?role=<role>.

Résout dette V1.1 Vague 4 (NewDriverPage) : le front doit pouvoir
proposer un picker de users au moment de rattacher un `fleet.Driver`.

Points vérifiés :
- Scoping tenant strict (A ne voit pas B et vice-versa).
- Filtre par rôle.
- Exclusion inconditionnelle du rôle CLIENT (safety).
- Rejet des non-authentifiés / non-staff.
- Pagination DRF standard.
- Exclusion des users inactifs.
"""
import pytest

from conftest import PASSWORD
from iam.models import User

pytestmark = pytest.mark.django_db

USERS_URL = "/api/v1/iam/users/"


def _make(tenant, email, role, first_name="Prenom", last_name="Nom", is_active=True):
    user = User.objects.create_user(
        email=email, password=PASSWORD, first_name=first_name, last_name=last_name,
        tenant=tenant, role=role,
    )
    if not is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])
    return user


def test_list_users_tenant_scoped(
    authenticated_client, user_admin_a, user_admin_b, user_driver_a, tenant_b
):
    """Un admin tenant A ne voit que les users du tenant A."""
    # user côté tenant B — ne doit JAMAIS apparaître pour admin A.
    _make(tenant_b, "driver.b@toupac.sn", User.Role.DRIVER, "Driver", "B")

    response = authenticated_client(user_admin_a).get(USERS_URL)

    assert response.status_code == 200, response.data
    emails = {row["email"] for row in response.data["results"]}
    assert user_admin_a.email in emails
    assert user_driver_a.email in emails
    assert all(not email.endswith(".b@toupac.sn") for email in emails), emails


def test_list_users_filter_role_driver(
    authenticated_client, user_admin_a, user_driver_a, user_dispatcher_a
):
    """`?role=driver` ne renvoie que les chauffeurs."""
    response = authenticated_client(user_admin_a).get(USERS_URL, {"role": "driver"})

    assert response.status_code == 200, response.data
    results = response.data["results"]
    assert len(results) >= 1
    assert all(row["role"] == "driver" for row in results)
    emails = {row["email"] for row in results}
    assert user_driver_a.email in emails
    assert user_dispatcher_a.email not in emails
    assert user_admin_a.email not in emails


def test_list_users_excludes_client_always(
    authenticated_client, user_admin_a, client_fatou
):
    """`?role=client` renvoie une liste vide — CLIENT est exclu en dur.

    Garde-fou contre un leak de la base passagers côté staff : même
    si on autorisait le filtre, le queryset exclut déjà CLIENT.
    """
    response = authenticated_client(user_admin_a).get(USERS_URL, {"role": "client"})

    assert response.status_code == 200, response.data
    assert response.data["results"] == []


def test_list_users_unauthenticated_rejected(api_client):
    """Pas de token → 401."""
    response = api_client.get(USERS_URL)
    assert response.status_code == 401


def test_list_users_non_staff_rejected(authenticated_client, user_driver_a):
    """Un chauffeur authentifié n'a pas vocation à énumérer les comptes.

    `is_staff=False` par défaut pour DRIVER (fixture racine) : la vue
    doit renvoyer 403 et non la liste.
    """
    response = authenticated_client(user_driver_a).get(USERS_URL)
    assert response.status_code == 403


def test_list_users_pagination(authenticated_client, user_admin_a, tenant_a):
    """Au-delà de 25 (PAGE_SIZE), la réponse paginée a `next` et 25 items."""
    for i in range(30):
        _make(tenant_a, f"extra.{i}@toupac.sn", User.Role.AGENT,
              first_name=f"Extra{i:02d}", last_name="Agent")

    response = authenticated_client(user_admin_a).get(USERS_URL)

    assert response.status_code == 200, response.data
    assert response.data["count"] >= 30
    assert len(response.data["results"]) == 25
    assert response.data["next"] is not None


def test_list_users_only_active(authenticated_client, user_admin_a, tenant_a):
    """Un user `is_active=False` est exclu — un compte désactivé ne doit
    pas remonter dans un picker, encore moins être rattaché à un chauffeur."""
    inactive = _make(
        tenant_a, "inactive.a@toupac.sn", User.Role.AGENT,
        first_name="Inactive", last_name="Zzz", is_active=False,
    )

    response = authenticated_client(user_admin_a).get(USERS_URL)

    assert response.status_code == 200, response.data
    emails = {row["email"] for row in response.data["results"]}
    assert inactive.email not in emails
