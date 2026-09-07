"""
TOUPAC IAM — Permissions plateforme : scopes et contrat du header X-Tenant-ID.

Le contrat de header est volontairement un 400 et non un 403 : oublier
`X-Tenant-ID` est une requête mal formée, pas un défaut d'autorisation, et un
403 enverrait l'intégrateur chercher un scope manquant sans rapport.
"""
import pytest

from iam.tests.platform_helpers import (
    TEST_IP,
    make_credential,
    platform_client,
    subscribe,
)

pytestmark = pytest.mark.django_db

ROUTES_URL = "/api/v1/voyage/routes/"
ORDERS_URL = "/api/v1/colis/orders/"
TENANTS_URL = "/api/v1/platform/tenants/"
HEALTH_URL = "/api/v1/platform/health/"
NOTIFICATIONS_URL = "/api/v1/platform/notifications/"


def test_scope_missing_from_credential_refused(tenant_a):
    """Une clé sans `platform:voyage:read` ne lit pas les routes."""
    _, secret = make_credential(scopes=["platform:colis:read", "platform:global:read"])
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_scope_present_grants_access(tenant_a):
    _, secret = make_credential(scopes=["platform:voyage:read"])
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200


def test_scopes_are_per_domain(tenant_a):
    """Un scope voyage n'ouvre pas colis : pas de fuite entre domaines."""
    _, secret = make_credential(scopes=["platform:voyage:read"])
    subscribe(tenant_a)
    client = platform_client(secret, tenant_a.slug)

    assert client.get(ROUTES_URL, REMOTE_ADDR=TEST_IP).status_code == 200
    assert client.get(ORDERS_URL, REMOTE_ADDR=TEST_IP).status_code == 403


def test_tenant_scopes_do_not_satisfy_platform_checks(tenant_a):
    """
    Une clé plateforme portant un scope tenant serait refusée.

    Les deux familles sont étanches : `voyage:read` n'est pas
    `platform:voyage:read`. Le modèle refuse d'ailleurs ce scope à l'émission —
    on vérifie ici l'étanchéité côté permission, sur une clé forcée en base.
    """
    from iam.models import PlatformCredential

    credential, secret = make_credential(scopes=["platform:global:read"])
    PlatformCredential.objects.filter(pk=credential.pk).update(
        platform_scopes=["voyage:read", "admin:*"],
    )
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_write_is_refused_even_with_every_scope(tenant_a):
    """Aucun scope d'écriture n'existe en V1 : la surface est en lecture seule."""
    _, secret = make_credential()
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).post(
        ORDERS_URL, {}, format="json", REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "lecture seule" in response.json()["detail"].lower()


def test_global_endpoint_refuses_x_tenant_id(tenant_a):
    _, secret = make_credential()
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 400
    assert "X-Tenant-ID" in str(response.json())


def test_global_endpoint_without_header_succeeds():
    _, secret = make_credential()

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200


def test_tenant_endpoint_refuses_missing_x_tenant_id():
    _, secret = make_credential()

    response = platform_client(secret).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 400
    assert "X-Tenant-ID" in str(response.json())


def test_tenant_endpoint_refuses_tenant_without_subscription(tenant_a):
    _, secret = make_credential()  # aucun TenantSubscription créé

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
    assert "abonné" in response.json()["detail"]


def test_tenant_endpoint_refuses_inactive_subscription(tenant_a):
    _, secret = make_credential()
    subscribe(tenant_a, is_active=False)

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_subscription_is_per_service(tenant_a):
    """Un abonnement à un autre service n'ouvre rien à celle-ci."""
    from iam.models import TenantSubscription

    _, secret = make_credential(service="chatbot-bi")
    TenantSubscription.objects.create(
        tenant=tenant_a, platform_service="autre-service", is_active=True,
    )

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_unannotated_endpoint_is_closed_by_default(tenant_a):
    """
    Un endpoint qui ne déclare aucun scope reste fermé aux clés plateforme.

    `/api/v1/notifications/templates/` participe au dispositif (il n'écrase pas
    `permission_classes`) mais ne déclare ni `api_scope_domain` ni
    `platform_required_scope` : le refus par défaut doit s'appliquer, sans quoi
    un oubli d'annotation ouvrirait l'endpoint au lieu de le fermer.
    """
    _, secret = make_credential()
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(
        "/api/v1/notifications/templates/", REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403


@pytest.mark.xfail(
    strict=True,
    reason="Dette connue et pré-existante : les vues qui redéfinissent "
           "permission_classes (MeView, logout, webhook, batch offline) sortent du "
           "dispositif de scopes — ni HasApiScope ni HasPlatformScope ne s'y appliquent. "
           "Vérifié : une ApiCredential tenant obtient elle aussi 200. La fuite se "
           "limite à l'identité du compte technique porteur, aucune donnée de tenant. "
           "Tracé dans DETTES.md ; retirer ce marqueur quand le trou sera fermé.",
)
def test_platform_key_cannot_reach_endpoints_outside_the_scope_dispositif(tenant_a):
    _, secret = make_credential()
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get("/api/v1/auth/me/", REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_notifications_endpoint_requires_its_own_scope(tenant_a):
    _, secret = make_credential(scopes=["platform:voyage:read"])
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(NOTIFICATIONS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_permissions_do_not_affect_jwt_users(tenant_a, user_admin_a, authenticated_client):
    """Les dispositifs plateforme sont sans effet sur une requête JWT ordinaire."""
    response = authenticated_client(user_admin_a).get(ROUTES_URL)

    assert response.status_code == 200
