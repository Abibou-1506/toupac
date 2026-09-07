"""Helpers partagés par les tests plateforme.

Fonctions simples uniquement — les fixtures pytest vivent dans
`iam/tests/conftest.py`, parce qu'importer une fixture dans un module de test
masque le paramètre du même nom.
"""
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from iam.models import PlatformCredential, TenantSubscription

#: IP utilisée par le client de test Django. `REMOTE_ADDR` vaut « 127.0.0.1 »
#: par défaut : l'allowlist des fixtures la couvre, et les tests qui veulent un
#: refus passent explicitement une autre IP.
TEST_IP = "127.0.0.1"
TEST_CIDR = "127.0.0.1/32"

SERVICE = "chatbot-bi"

FULL_SCOPES = [
    "platform:voyage:read", "platform:colis:read", "platform:tracking:read",
    "platform:billing:read", "platform:notifications:read", "platform:global:read",
]


def grant_admin_permissions(user):
    """is_staff seul ne donne accès à rien : l'admin exige une permission par modèle."""
    user.user_permissions.set(Permission.objects.filter(content_type__app_label="iam"))
    return user


def admin_client(user):
    client = Client()
    client.force_login(grant_admin_permissions(user))
    return client


def make_credential(scopes=None, allowed_ips=None, service=SERVICE, **overrides):
    """Émet une clé plateforme utilisable et retourne (credential, secret_en_clair)."""
    return PlatformCredential.issue(
        name=overrides.pop("name", "Chatbot BI test"),
        platform_service=service,
        platform_scopes=scopes if scopes is not None else FULL_SCOPES,
        allowed_ips=allowed_ips if allowed_ips is not None else [TEST_CIDR],
        expires_at=overrides.pop("expires_at", timezone.now() + timedelta(days=90)),
        **overrides,
    )


def subscribe(tenant, service=SERVICE, is_active=True):
    return TenantSubscription.objects.create(
        tenant=tenant, platform_service=service, is_active=is_active,
    )


def platform_client(secret, tenant_slug=None):
    """APIClient portant la clé plateforme, et le tenant visé si fourni."""
    from rest_framework.test import APIClient

    client = APIClient()
    headers = {"HTTP_X_API_KEY": secret}
    if tenant_slug is not None:
        headers["HTTP_X_TENANT_ID"] = tenant_slug
    client.credentials(**headers)
    return client
