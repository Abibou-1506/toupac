"""
TOUPAC IAM — Émission d'une clé plateforme depuis l'admin.

Même exigence que pour les clés tenant : le secret arrive une fois à
l'opérateur et ne fuit nulle part ailleurs. S'y ajoute la réserve au superadmin
— une clé plateforme ouvre les données de toutes les compagnies abonnées.
"""
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from iam.models import AuditLog, PlatformAuditLog, PlatformCredential
from iam.tests.platform_helpers import admin_client

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/iam/platformcredential/add/"
CHANGELIST_URL = "/admin/iam/platformcredential/"
SESSION_KEY = "_toupac_platform_credential_reveal"


def create_credential(client, name="Chatbot BI prod", service="chatbot-bi",
                      scopes=("platform:voyage:read", "platform:global:read"),
                      allowed_ips="52.34.10.5/32", expires_in_days=None):
    """POST le formulaire d'ajout. `expires_in_days=None` n'envoie aucune date."""
    payload = {
        "name": name,
        "platform_service": service,
        "platform_scopes": list(scopes),
        "allowed_ips": allowed_ips,
        "expires_at_0": "",
        "expires_at_1": "",
    }
    if expires_in_days is not None:
        expires_at = timezone.now() + timedelta(days=expires_in_days)
        payload["expires_at_0"] = expires_at.strftime("%Y-%m-%d")
        payload["expires_at_1"] = expires_at.strftime("%H:%M:%S")
    return client.post(ADD_URL, payload)


def reveal_url(credential):
    return reverse("admin:iam_platformcredential_reveal", args=[credential.pk])


# ─── Accès ───

def test_superadmin_can_add_platform_credential(superadmin):
    response = create_credential(admin_client(superadmin))

    assert response.status_code == 302
    credential = PlatformCredential.objects.get(name="Chatbot BI prod")
    assert credential.platform_service == "chatbot-bi"
    assert credential.allowed_ips == ["52.34.10.5/32"]
    assert credential.created_by_id == superadmin.id
    assert response["Location"] == reveal_url(credential)


def test_tenant_admin_cannot_access_platform_credential_admin(user_admin_a):
    client = admin_client(user_admin_a)

    assert client.get(CHANGELIST_URL).status_code == 403
    assert client.get(ADD_URL).status_code == 403


def test_tenant_admin_cannot_access_the_platform_audit_admin(user_admin_a):
    assert admin_client(user_admin_a).get("/admin/iam/platformauditlog/").status_code == 403


def test_subscription_admin_no_longer_exists(superadmin):
    """Le concept d'abonnement est retiré (USR-4) : plus aucune page ne l'expose."""
    assert admin_client(superadmin).get("/admin/iam/tenantsubscription/").status_code == 404


# ─── Révélation du secret ───

def test_reveal_page_shows_secret_with_platform_prefix(superadmin):
    client = admin_client(superadmin)
    create_credential(client)
    credential = PlatformCredential.objects.get(name="Chatbot BI prod")
    secret = client.session[SESSION_KEY]["secret"]

    response = client.get(reveal_url(credential))

    assert response.status_code == 200
    body = response.content.decode()
    assert credential.key_prefix.startswith("tpc_platform_")
    assert secret.startswith(f"{credential.key_prefix}.")
    assert secret in body
    assert "X-Tenant-ID" in body


def test_platform_credential_reveal_one_shot(superadmin):
    client = admin_client(superadmin)
    create_credential(client)
    credential = PlatformCredential.objects.get(name="Chatbot BI prod")
    secret = client.session[SESSION_KEY]["secret"]

    assert client.get(reveal_url(credential)).status_code == 200

    second = client.get(reveal_url(credential))

    assert second.status_code == 302
    assert second["Location"] == reverse("admin:iam_platformcredential_change", args=[credential.pk])
    assert secret not in second.content.decode()
    assert SESSION_KEY not in client.session


def test_secret_plaintext_not_in_db_nor_audit(superadmin):
    client = admin_client(superadmin)
    create_credential(client)
    credential = PlatformCredential.objects.get(name="Chatbot BI prod")
    secret = client.session[SESSION_KEY]["secret"]

    assert secret not in credential.key_hash
    assert secret.split(".", 1)[1] not in credential.key_hash

    audit = AuditLog.objects.get(action="platform_credential.issued")
    assert audit.resource_type == "PlatformCredential"
    assert audit.resource_id == credential.id
    assert audit.user_id == superadmin.id
    assert audit.tenant_id is None  # une clé plateforme n'appartient à aucun tenant
    assert secret.split(".", 1)[1] not in json.dumps(audit.changes)


# ─── Garde-fous du formulaire ───

def test_unknown_platform_service_refused(superadmin):
    before = PlatformCredential.objects.count()

    response = create_credential(admin_client(superadmin), service="foobar")

    assert response.status_code == 200  # formulaire réaffiché
    assert PlatformCredential.objects.count() == before


def test_expires_at_too_soon_refused(superadmin):
    before = PlatformCredential.objects.count()

    response = create_credential(admin_client(superadmin), expires_in_days=0)

    assert response.status_code == 200
    assert "12 heures" in response.content.decode()
    assert PlatformCredential.objects.count() == before


def test_empty_allowlist_accepted_in_production(superadmin, settings):
    """Un partenaire sans adresse de sortie stable doit pouvoir recevoir une clé."""
    settings.DEBUG = False

    response = create_credential(admin_client(superadmin), allowed_ips="")

    assert response.status_code == 302
    assert PlatformCredential.objects.get(name="Chatbot BI prod").allowed_ips == []


def test_invalid_cidr_refused(superadmin):
    before = PlatformCredential.objects.count()

    response = create_credential(admin_client(superadmin), allowed_ips="pas-un-cidr")

    assert response.status_code == 200
    assert "CIDR invalide" in response.content.decode()
    assert PlatformCredential.objects.count() == before


def test_add_form_offers_no_super_scope(superadmin):
    """La doctrine est visible dans le formulaire, pas seulement dans le code."""
    body = admin_client(superadmin).get(ADD_URL).content.decode()

    assert 'value="platform:voyage:read"' in body
    # L'écriture est ouverte depuis USR-4 ; le super-scope ne l'est toujours pas.
    assert 'value="platform:voyage:write"' in body
    assert 'value="platform:customer:read"' in body
    assert 'value="platform:*"' not in body
    assert 'value="platform:notifications:emit"' not in body


def test_add_form_does_not_prefill_an_expiry(superadmin):
    """Le défaut est une clé sans échéance : le champ arrive vide."""
    body = admin_client(superadmin).get(ADD_URL).content.decode()

    assert 'name="expires_at_0" value=' not in body


def test_credential_can_be_issued_without_expiry(superadmin):
    response = create_credential(admin_client(superadmin), expires_in_days=None)

    assert response.status_code == 302
    assert PlatformCredential.objects.get(name="Chatbot BI prod").expires_at is None


# ─── Journal d'audit plateforme ───

def test_platform_audit_log_admin_read_only(superadmin):
    client = admin_client(superadmin)

    assert client.get("/admin/iam/platformauditlog/").status_code == 200
    assert client.get("/admin/iam/platformauditlog/add/").status_code == 403


def test_platform_audit_log_admin_forbids_change_and_delete(superadmin):
    from django.contrib import admin as django_admin

    model_admin = django_admin.site._registry[PlatformAuditLog]
    request = type("R", (), {"user": superadmin})()

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


# ─── Journal : le client représenté ───

def test_audit_admin_exposes_the_acting_user(superadmin):
    """La colonne doit être visible et filtrable : c'est ce qu'on cherche en incident."""
    from django.contrib import admin as django_admin

    from iam.models import PlatformAuditLog

    model_admin = django_admin.site._registry[PlatformAuditLog]

    assert "acting_user" in model_admin.list_display
    assert "acting_user" in model_admin.list_filter
    assert admin_client(superadmin).get("/admin/iam/platformauditlog/").status_code == 200
