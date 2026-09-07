"""
TOUPAC IAM — L'admin refuse les combinaisons rôle/tenant incohérentes.

Trois barrières superposées, testées séparément : le menu déroulant restreint
(interface), `save_model` (POST forgé), et `User.clean()` relayé par le
formulaire (cohérence rôle/tenant). Chacune seule laisserait passer un cas.
"""
import pytest

from iam.models import User
from iam.tests.platform_helpers import admin_client

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/iam/user/add/"

PASSWORD = "TestPass#2026"


def post_user(client, role, tenant=None, email="nouveau@example.sn", phone=""):
    payload = {
        "email": email,
        "first_name": "Nouveau",
        "last_name": "Compte",
        "phone": phone,
        "role": role,
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    if tenant is not None:
        payload["tenant"] = str(tenant.pk)
    return client.post(ADD_URL, payload)


# ─── Superadmin : la cohérence rôle/tenant est vérifiée ───

def test_superadmin_cannot_save_client_with_tenant(superadmin, tenant_a):
    before = User.objects.filter(role=User.Role.CLIENT).count()

    response = post_user(admin_client(superadmin), User.Role.CLIENT, tenant=tenant_a)

    assert response.status_code == 200  # formulaire réaffiché, pas de redirection
    assert User.objects.filter(role=User.Role.CLIENT).count() == before
    assert "errorlist" in response.content.decode()


def test_superadmin_cannot_save_driver_without_tenant(superadmin):
    before = User.objects.filter(role=User.Role.DRIVER).count()

    response = post_user(admin_client(superadmin), User.Role.DRIVER, tenant=None)

    assert response.status_code == 200
    assert User.objects.filter(role=User.Role.DRIVER).count() == before
    assert "errorlist" in response.content.decode()


def test_superadmin_can_save_client_without_tenant(superadmin):
    response = post_user(admin_client(superadmin), User.Role.CLIENT, tenant=None)

    assert response.status_code == 302
    created = User.objects.get(email="nouveau@example.sn")
    assert created.role == User.Role.CLIENT
    assert created.tenant is None


def test_superadmin_can_save_driver_with_tenant(superadmin, tenant_a):
    response = post_user(admin_client(superadmin), User.Role.DRIVER, tenant=tenant_a)

    assert response.status_code == 302
    assert User.objects.get(email="nouveau@example.sn").tenant == tenant_a


# ─── Admin de compagnie : les rôles attribuables sont restreints ───

def test_tenant_admin_role_dropdown_excludes_client_and_superadmin(user_admin_a):
    body = admin_client(user_admin_a).get(ADD_URL).content.decode()

    assert 'value="client"' not in body
    assert 'value="superadmin"' not in body
    assert 'value="service_account"' not in body
    # Les rôles internes restent proposés.
    assert 'value="driver"' in body
    assert 'value="dispatcher"' in body


def test_superadmin_role_dropdown_offers_every_role(superadmin):
    body = admin_client(superadmin).get(ADD_URL).content.decode()

    for role in User.Role.values:
        assert f'value="{role}"' in body


@pytest.mark.parametrize(
    "forged_role", [User.Role.CLIENT, User.Role.SUPERADMIN, User.Role.SERVICE_ACCOUNT],
)
def test_tenant_admin_cannot_forge_a_restricted_role_by_post(user_admin_a, forged_role):
    """
    Le POST forgé est refusé par la validation du champ, pas seulement par le HTML.

    Restreindre les `choices` ne fait pas que masquer des options : Django
    valide la valeur reçue contre cette même liste. Le refus prend donc la forme
    d'une erreur de formulaire (200 + errorlist) plutôt que d'un 403.
    """
    before = User.objects.filter(role=forged_role).count()

    response = post_user(admin_client(user_admin_a), forged_role, tenant=None)

    assert response.status_code == 200
    assert "errorlist" in response.content.decode()
    assert User.objects.filter(role=forged_role).count() == before


def test_save_model_refuses_a_restricted_role_programmatically(user_admin_a, tenant_a):
    """
    Dernier verrou, hors formulaire.

    Si un jour les `choices` cessaient d'être restreints — refonte du
    formulaire, action d'admin sur mesure — `save_model` refuserait encore.
    """
    from django.contrib import admin as django_admin
    from django.core.exceptions import PermissionDenied

    model_admin = django_admin.site._registry[User]
    request = type("R", (), {"user": user_admin_a})()
    forged = User(email="pirate@example.sn", role=User.Role.CLIENT, tenant=None)

    with pytest.raises(PermissionDenied):
        model_admin.save_model(request, forged, form=None, change=False)


def test_tenant_admin_can_create_an_internal_role(user_admin_a, tenant_a):
    """Le cas nominal reste ouvert : l'admin recrute dans sa compagnie."""
    response = post_user(admin_client(user_admin_a), User.Role.AGENT, tenant=tenant_a)

    assert response.status_code == 302
    created = User.objects.get(email="nouveau@example.sn")
    assert created.role == User.Role.AGENT
    assert created.tenant == tenant_a


def test_client_is_hidden_from_tenant_admin_user_list(user_admin_a, client_fatou):
    """Un client global n'appartient à aucune compagnie : il n'a rien à y faire."""
    response = admin_client(user_admin_a).get("/admin/iam/user/")

    assert response.status_code == 200
    assert str(client_fatou.pk) not in response.content.decode()


def test_client_is_visible_to_superadmin(superadmin, client_fatou):
    response = admin_client(superadmin).get("/admin/iam/user/")

    assert response.status_code == 200
    assert str(client_fatou.pk) in response.content.decode()
