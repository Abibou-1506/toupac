"""
TOUPAC IAM — Backend d'authentification par clé plateforme.

Les tests passent par de vraies requêtes HTTP plutôt que d'appeler
`authenticate()` à la main : le contrat qui compte est le code de retour vu par
l'intégrateur, et il dépend d'interactions (middleware tenant, ordre des
backends, gestionnaire d'exceptions) qu'un appel direct court-circuiterait.

L'IP source est pilotée via `REMOTE_ADDR`, que le client de test Django accepte
en argument de requête — pas de middleware simulé ni de monkeypatch.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from iam.models import PLATFORM_BOT_EMAIL, ApiCredential, PlatformAuditLog
from iam.tests.platform_helpers import (
    TEST_IP,
    make_credential,
    platform_client,
)

pytestmark = pytest.mark.django_db

ROUTES_URL = "/api/v1/voyage/routes/"
HEALTH_URL = "/api/v1/platform/health/"


def test_valid_key_authenticates_and_resolves_tenant(tenant_a):
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200


def test_authenticated_request_carries_platform_bot_and_credential(tenant_a):
    credential, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    # `request.user` et `request.auth` ne sont pas observables depuis la réponse :
    # on les vérifie par leurs effets, la trace d'audit portant la bonne clé et
    # le bon tenant résolu.
    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    assert log.tenant_context_id == tenant_a.id


def test_key_with_tenant_prefix_falls_through_to_tenant_backend(tenant_a, user_admin_a):
    """
    Une clé tenant ne doit pas être happée par le backend plateforme.

    Le préfixe distinct permet à `PlatformApiKeyAuthentication` de rendre la main
    sans requête SQL ; ce test vérifie que la chaîne continue bien jusqu'au
    backend tenant, qui authentifie normalement.
    """
    credential, secret = ApiCredential.issue(
        tenant=tenant_a, name="Clé tenant", scopes=["voyage:read"],
        user=tenant_a.get_or_create_service_account(),
    )
    assert credential.key_prefix.startswith("tpc_")
    assert not credential.key_prefix.startswith("tpc_platform_")

    response = platform_client(secret).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    # Aucune trace plateforme : la requête n'a pas touché ce dispositif.
    assert PlatformAuditLog.objects.count() == 0


def test_unknown_platform_key_refused():
    make_credential()

    response = platform_client("tpc_platform_deadbeef.mauvais-secret").get(
        HEALTH_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 401


def test_wrong_secret_on_valid_prefix_refused():
    credential, _ = make_credential()

    response = platform_client(f"{credential.key_prefix}.mauvais-secret").get(
        HEALTH_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 401


def test_key_without_separator_refused():
    make_credential()

    response = platform_client("tpc_platform_deadbeef").get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 401


def test_ip_not_in_allowlist_refused():
    """403 et non 401 : la clé est bonne, c'est l'origine qui est refusée."""
    _, secret = make_credential(allowed_ips=["52.34.10.5/32"])

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR="8.8.8.8")

    assert response.status_code == 403
    assert "8.8.8.8" in response.json()["detail"]


def test_empty_allowlist_accepts_any_origin_in_production(settings):
    """
    Une clé sans restriction d'origine fonctionne partout, y compris en production.

    Le garde-fou d'origine reste recommandé, mais il ne peut pas être obligatoire :
    un service partenaire sans adresse de sortie stable n'a rien à déclarer.
    """
    settings.DEBUG = False
    _, secret = make_credential(allowed_ips=[])

    assert platform_client(secret).get(HEALTH_URL, REMOTE_ADDR="8.8.8.8").status_code == 200
    assert platform_client(secret).get(HEALTH_URL, REMOTE_ADDR="1.2.3.4").status_code == 200


def test_key_without_expiry_never_expires():
    """Le cas nominal : la clé vit jusqu'à sa révocation."""
    credential, secret = make_credential()
    assert credential.expires_at is None

    assert platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP).status_code == 200


def test_forwarded_for_header_is_used_as_source_ip():
    """Derrière le reverse-proxy, l'IP réelle est la première de X-Forwarded-For."""
    _, secret = make_credential(allowed_ips=["52.34.10.5/32"])
    client = platform_client(secret)

    allowed = client.get(
        HEALTH_URL, REMOTE_ADDR="10.9.9.9", HTTP_X_FORWARDED_FOR="52.34.10.5, 10.9.9.9",
    )
    refused = client.get(
        HEALTH_URL, REMOTE_ADDR="52.34.10.5", HTTP_X_FORWARDED_FOR="8.8.8.8, 10.9.9.9",
    )

    assert allowed.status_code == 200
    assert refused.status_code == 403


def test_expired_key_refused():
    credential, secret = make_credential()
    # Contourne clean() : on simule le passage du temps, pas une saisie invalide.
    type(credential).objects.filter(pk=credential.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 401
    assert "expirée" in response.json()["detail"].lower()


def test_inactive_key_refused():
    credential, secret = make_credential()
    type(credential).objects.filter(pk=credential.pk).update(is_active=False)

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 401


def test_tenant_context_resolved_from_header(tenant_a, tenant_b):
    """Le slug du header choisit le tenant — et lui seul."""
    _, secret = make_credential()

    platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    log = PlatformAuditLog.objects.get()
    assert log.tenant_context_id == tenant_a.id


def test_unknown_tenant_slug_refused(tenant_a):
    _, secret = make_credential()

    response = platform_client(secret, "compagnie-fantome").get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
    assert "compagnie-fantome" in response.json()["detail"]


def test_suspended_tenant_refused(tenant_suspended):
    """SUSPENDED est le levier de coupure commercial : il ferme aussi la plateforme."""
    _, secret = make_credential()

    response = platform_client(secret, tenant_suspended.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_last_used_at_is_updated(tenant_a):
    credential, secret = make_credential()
    assert credential.last_used_at is None

    platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    credential.refresh_from_db()
    assert credential.last_used_at is not None


def test_platform_bot_is_the_authenticated_user(tenant_a):
    """Le porteur est le compte technique global, jamais un utilisateur du tenant."""
    from iam.models import User

    User.objects.filter(email=PLATFORM_BOT_EMAIL).delete()
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    # Recréé à la volée par l'authentification, malgré la suppression.
    bot = User.objects.get(email=PLATFORM_BOT_EMAIL)
    assert bot.tenant is None
