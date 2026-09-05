"""
TOUPAC IAM — Émission d'une clé API depuis l'admin, avec révélation unique.

Le secret n'existe en clair que le temps d'un aller-retour : ces tests
vérifient qu'il arrive bien à l'opérateur une fois, et qu'il ne fuit nulle
part ailleurs (base, journal d'audit, seconde lecture).
"""
import json

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core.management.commands.seed_demo import STAFF_GROUP
from iam.models import ApiCredential, AuditLog, User
from iam.scopes import AVAILABLE_SCOPES

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/iam/apicredential/add/"
SESSION_KEY = "_toupac_api_credential_reveal"


# ─── Fixtures et helpers locaux ───

def grant_admin_permissions(user):
    """is_staff seul ne donne accès à rien : l'admin exige une permission par modèle."""
    user.user_permissions.set(Permission.objects.filter(content_type__app_label="iam"))
    return user


def admin_client(user):
    client = Client()
    client.force_login(grant_admin_permissions(user))
    return client


@pytest.fixture
def superadmin():
    return User.objects.create_user(
        email="super@toupac.sn", password="TestPass#2026", first_name="Super",
        last_name="Admin", tenant=None, role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True,
    )


def create_credential(client, tenant, bearer, name="Clé chatbot BI", scopes=("voyage:read",)):
    """POST le formulaire d'ajout. Retourne la réponse (302 attendu)."""
    return client.post(ADD_URL, {
        "name": name,
        "tenant": str(tenant.pk),
        "user": str(bearer.pk),
        "scopes": list(scopes),
        "expires_at_0": "",
        "expires_at_1": "",
    })


def reveal_url(credential):
    return reverse("admin:iam_apicredential_reveal", args=[credential.pk])


# ─── Tests ───

def test_add_form_lists_all_scopes_as_checkboxes(superadmin):
    response = admin_client(superadmin).get(ADD_URL)

    assert response.status_code == 200
    body = response.content.decode()
    assert 'type="checkbox"' in body
    missing = [scope for scope in AVAILABLE_SCOPES if f'value="{scope}"' not in body]
    assert missing == []


def test_add_valid_form_creates_credential_and_redirects_to_reveal(superadmin, tenant_a, user_admin_a):
    response = create_credential(admin_client(superadmin), tenant_a, user_admin_a)

    assert response.status_code == 302
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    assert credential.tenant_id == tenant_a.id
    assert credential.scopes == ["voyage:read"]
    assert response["Location"] == reveal_url(credential)


def test_reveal_page_shows_secret_with_tpc_prefix(superadmin, tenant_a, user_admin_a):
    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    secret = client.session[SESSION_KEY]["secret"]

    response = client.get(reveal_url(credential))

    assert response.status_code == 200
    body = response.content.decode()
    assert secret.startswith(f"{credential.key_prefix}.")
    assert credential.key_prefix.startswith("tpc_")
    assert secret in body
    assert "<pre" in body


def test_reveal_page_second_get_no_longer_shows_secret(superadmin, tenant_a, user_admin_a):
    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    secret = client.session[SESSION_KEY]["secret"]

    first = client.get(reveal_url(credential))
    assert first.status_code == 200

    second = client.get(reveal_url(credential))

    assert second.status_code == 302
    assert second["Location"] == reverse("admin:iam_apicredential_change", args=[credential.pk])
    body = second.content.decode()
    assert secret not in body
    assert f"{credential.key_prefix}." not in body


def test_secret_plaintext_not_in_db(superadmin, tenant_a, user_admin_a):
    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    secret = client.session[SESSION_KEY]["secret"]

    assert secret not in credential.key_hash
    assert secret.split(".", 1)[1] not in credential.key_hash
    assert credential.key_hash.startswith("pbkdf2_")


def test_audit_log_created_without_secret(superadmin, tenant_a, user_admin_a):
    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    secret = client.session[SESSION_KEY]["secret"]

    audit = AuditLog.objects.get(action="api_credential.issued")

    assert audit.resource_type == "ApiCredential"
    assert audit.resource_id == credential.id
    assert audit.tenant_id == tenant_a.id
    assert audit.user_id == superadmin.id
    assert set(audit.changes) == {"name", "scopes", "key_prefix", "expires_at"}
    assert audit.changes["key_prefix"] == credential.key_prefix

    serialized = json.dumps(audit.changes)
    assert secret not in serialized
    assert secret.split(".", 1)[1] not in serialized


def test_tenant_admin_cannot_forge_tenant_field(user_admin_a, tenant_a, tenant_b):
    """Le tenant est readonly hors superadmin : la valeur postée est ignorée."""
    response = create_credential(admin_client(user_admin_a), tenant_b, user_admin_a, name="Clé forgée")

    assert response.status_code == 302
    credential = ApiCredential.objects.get(name="Clé forgée")
    assert credential.tenant_id == tenant_a.id


def test_credential_without_bearer_is_refused(superadmin, tenant_a):
    """
    ApiKeyAuthentication rejette une clé orpheline : sans ce garde-fou, le
    formulaire produisait des clés créées sans erreur puis 401 à l'usage.
    """
    response = admin_client(superadmin).post(ADD_URL, {
        "name": "Clé sans porteur", "tenant": str(tenant_a.pk),
        "scopes": ["voyage:read"], "expires_at_0": "", "expires_at_1": "",
    })

    assert response.status_code == 200  # formulaire réaffiché
    assert not ApiCredential.objects.filter(name="Clé sans porteur").exists()


def test_bearer_from_another_tenant_is_refused(superadmin, tenant_a, user_admin_b):
    """Un porteur d'une autre compagnie ferait diverger request.user.tenant du tenant de la clé."""
    response = create_credential(
        admin_client(superadmin), tenant_a, user_admin_b, name="Clé porteur croisé",
    )

    assert response.status_code == 200
    assert "autre compagnie" in response.content.decode()
    assert not ApiCredential.objects.filter(name="Clé porteur croisé").exists()


def test_issued_key_actually_authenticates(superadmin, tenant_a, user_admin_a):
    """Contrôle de bout en bout : la clé émise par l'admin ouvre bien l'API."""
    from rest_framework.test import APIClient

    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    secret = client.session[SESSION_KEY]["secret"]

    api = APIClient()
    api.credentials(HTTP_X_API_KEY=secret)

    assert api.get("/api/v1/voyage/routes/").status_code == 200


def test_admin_scope_forbidden_for_tenant_admin(user_admin_a, tenant_a):
    """
    `admin:*` est réservé aux intégrations internes TOUPAC.

    Aucune compagnie cliente n'a de cas d'usage légitime : le refus est
    catégorique pour tout émetteur non superadmin.
    """
    before = ApiCredential.objects.count()

    response = create_credential(
        admin_client(user_admin_a), tenant_a, user_admin_a,
        name="Clé tout-puissante", scopes=("admin:*",),
    )

    assert response.status_code == 200  # formulaire réaffiché, pas de redirection
    body = response.content.decode()
    assert "admin:*" in body
    assert "intégrations internes TOUPAC" in body
    assert ApiCredential.objects.count() == before


def test_admin_scope_allowed_for_superadmin(superadmin, tenant_a, user_admin_a):
    response = create_credential(
        admin_client(superadmin), tenant_a, user_admin_a,
        name="Outillage interne", scopes=("admin:*",),
    )

    assert response.status_code == 302
    credential = ApiCredential.objects.get(name="Outillage interne")
    assert credential.scopes == ["admin:*"]
    assert response["Location"] == reveal_url(credential)


def test_credential_without_bearer_passes_model_validation(tenant_a):
    """
    `blank=True` aligne le modèle sur la base : SET_NULL peut laisser une clé
    sans porteur, `full_clean()` ne doit donc pas l'interdire. La contrainte
    « porteur obligatoire » vit dans le formulaire et l'authentificateur.
    """
    credential = ApiCredential(
        tenant=tenant_a, name="Clé orpheline", key_prefix="tpc_xxxx",
        key_hash="x", scopes=["voyage:read"],
    )

    credential.full_clean(exclude=["key_hash"])  # ne lève pas


def test_seed_demo_staff_group_has_apicredential_permissions():
    """
    Sans ces permissions, un admin de compagnie reçoit un 403 sur
    /admin/iam/apicredential/ — la démo lead était impossible sur son compte.

    `--only` plutôt qu'un seed complet : celui-ci signe 428 QR en RS256 et
    prendrait près d'une minute pour une vérification qui ne touche qu'au
    groupe de permissions.
    """
    call_command("seed_demo", only="tenants", quiet=True)
    call_command("seed_demo", only="users", quiet=True)

    group = Group.objects.get(name=STAFF_GROUP)
    codenames = set(group.permissions.values_list("codename", flat=True))

    assert {
        "add_apicredential", "change_apicredential",
        "view_apicredential", "delete_apicredential",
    } <= codenames
    # L'ouverture reste chirurgicale : pas de gestion d'utilisateurs.
    assert "add_user" not in codenames
    assert "change_user" not in codenames


def test_reveal_url_rejects_after_5_minutes(superadmin, tenant_a, user_admin_a):
    client = admin_client(superadmin)
    create_credential(client, tenant_a, user_admin_a)
    credential = ApiCredential.objects.get(name="Clé chatbot BI")
    secret = client.session[SESSION_KEY]["secret"]

    session = client.session
    session[SESSION_KEY] = {**session[SESSION_KEY], "expires_epoch": 0}
    session.save()

    response = client.get(reveal_url(credential))

    assert response.status_code == 302
    assert response["Location"] == reverse("admin:iam_apicredential_change", args=[credential.pk])
    assert secret not in response.content.decode()
    # Le secret est purgé même quand l'affichage est refusé.
    assert SESSION_KEY not in client.session
