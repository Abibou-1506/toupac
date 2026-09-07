"""Helpers partagés par les tests plateforme.

Fonctions simples uniquement — les fixtures pytest vivent dans
`iam/tests/conftest.py`, parce qu'importer une fixture dans un module de test
masque le paramètre du même nom.
"""

from django.contrib.auth.models import Permission
from django.test import Client

from iam.models import PlatformCredential

#: IP utilisée par le client de test Django. `REMOTE_ADDR` vaut « 127.0.0.1 »
#: par défaut : l'allowlist des fixtures la couvre, et les tests qui veulent un
#: refus passent explicitement une autre IP.
TEST_IP = "127.0.0.1"
TEST_CIDR = "127.0.0.1/32"

SERVICE = "chatbot-bi"

FULL_SCOPES = [
    "platform:voyage:read", "platform:voyage:write",
    "platform:colis:read", "platform:colis:write",
    "platform:tracking:read",
    "platform:billing:read", "platform:billing:write",
    "platform:notifications:read",
    "platform:customer:read",
    "platform:global:read",
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
        # Sans échéance par défaut, comme en production depuis USR-4. Les tests
        # qui vérifient l'expiration en posent une explicitement.
        expires_at=overrides.pop("expires_at", None),
        **overrides,
    )


def platform_client(secret, tenant_slug=None, acting_email=None, acting_phone=None):
    """APIClient portant la clé plateforme, le tenant visé et le client représenté."""
    from rest_framework.test import APIClient

    client = APIClient()
    headers = {"HTTP_X_API_KEY": secret}
    if tenant_slug is not None:
        headers["HTTP_X_TENANT_ID"] = tenant_slug
    if acting_email is not None:
        headers["HTTP_X_ACTING_USER_EMAIL"] = acting_email
    if acting_phone is not None:
        headers["HTTP_X_ACTING_USER_PHONE"] = acting_phone
    client.credentials(**headers)
    return client
