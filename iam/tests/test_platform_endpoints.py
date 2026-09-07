"""
TOUPAC IAM — Endpoints plateforme et journal d'audit.

Le journal est la mitigation n°4 de la note de design : il doit couvrir les
échecs autant que les succès, sans quoi il raterait précisément la compromission
qu'il est censé détecter.
"""
import pytest

from iam.models import PlatformAuditLog
from iam.tests.platform_helpers import (
    TEST_IP,
    make_credential,
    platform_client,
    subscribe,
)

pytestmark = pytest.mark.django_db

TENANTS_URL = "/api/v1/platform/tenants/"
HEALTH_URL = "/api/v1/platform/health/"
NOTIFICATIONS_URL = "/api/v1/platform/notifications/"
ROUTES_URL = "/api/v1/voyage/routes/"


# ─── Endpoints globaux ───

def test_platform_tenants_lists_subscribed_only(tenant_a, tenant_b, tenant_trial):
    _, secret = make_credential()
    subscribe(tenant_a)
    subscribe(tenant_b, is_active=False)   # abonnement révoqué
    # tenant_trial : jamais abonné

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    assert response.json() == {"tenants": [{"slug": tenant_a.slug, "name": tenant_a.name}]}


def test_platform_tenants_is_scoped_to_the_key_service(tenant_a, tenant_b):
    """Une clé ne découvre que les tenants abonnés à *son* service."""
    from iam.models import TenantSubscription

    _, secret = make_credential(service="chatbot-bi")
    subscribe(tenant_a, service="chatbot-bi")
    TenantSubscription.objects.create(
        tenant=tenant_b, platform_service="autre-service", is_active=True,
    )

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    slugs = [t["slug"] for t in response.json()["tenants"]]
    assert slugs == [tenant_a.slug]


def test_platform_health_returns_expiry_info():
    credential, secret = make_credential(scopes=["platform:global:read"])

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    body = response.json()
    assert body["platform_service"] == credential.platform_service
    assert body["scopes"] == ["platform:global:read"]
    assert 89 <= body["days_until_expiry"] <= 90
    assert body["expires_at"] is not None


def test_platform_health_requires_global_scope():
    _, secret = make_credential(scopes=["platform:voyage:read"])

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


# ─── Endpoint tenant-scopé ───

def test_platform_notifications_returns_tenant_items_only(tenant_a, tenant_b, user_admin_a, user_admin_b):
    from notifications.models import Notification

    def make(tenant, user, title):
        return Notification.objects.create(
            tenant=tenant, event_code="notif.payment.confirmed.v1", recipient_user=user,
            trigger_scope=Notification.TriggerScope.USER,
            priority=Notification.Priority.HIGH, title=title, body="…",
        )

    make(tenant_a, user_admin_a, "Pour A")
    make(tenant_b, user_admin_b, "Pour B")

    _, secret = make_credential()
    subscribe(tenant_a)

    response = platform_client(secret, tenant_a.slug).get(NOTIFICATIONS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Pour A"]


# ─── Journal d'audit ───

def test_audit_log_created_on_each_call(tenant_a):
    credential, secret = make_credential()
    subscribe(tenant_a)

    platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    assert log.tenant_context_id == tenant_a.id
    assert log.endpoint == ROUTES_URL
    assert log.method == "GET"
    assert log.ip == TEST_IP
    assert log.status_code == 200
    assert log.latency_ms is not None and log.latency_ms >= 0


def test_audit_log_created_even_on_403_ip_refusal():
    """Un refus d'IP est exactement l'événement que le journal doit capturer."""
    credential, secret = make_credential(allowed_ips=["52.34.10.5/32"])

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR="8.8.8.8")

    assert response.status_code == 403
    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    assert log.status_code == 403
    assert log.ip == "8.8.8.8"
    # Aucun contexte tenant : la requête n'est jamais allée jusque-là.
    assert log.tenant_context_id is None


def test_audit_log_created_on_missing_subscription(tenant_a):
    """« A tenté d'accéder à un tenant non abonné » doit rester visible."""
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
    log = PlatformAuditLog.objects.get()
    assert log.status_code == 403
    assert log.tenant_context_id is None


def test_audit_log_created_on_401_expired_key():
    from datetime import timedelta

    from django.utils import timezone

    from iam.models import PlatformCredential

    credential, secret = make_credential()
    PlatformCredential.objects.filter(pk=credential.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 401
    assert PlatformAuditLog.objects.filter(credential=credential, status_code=401).exists()


def test_no_audit_log_for_non_platform_requests(tenant_a, user_admin_a, authenticated_client):
    """Le journal ne trace que la plateforme : une requête JWT n'y figure pas."""
    authenticated_client(user_admin_a).get(ROUTES_URL)

    assert PlatformAuditLog.objects.count() == 0


# ─── Bout en bout ───

def test_e2e_chatbot_flow(tenant_a, tenant_b):
    """
    Le parcours complet promis à l'équipe chatbot.

    Émettre une clé, abonner un tenant, découvrir les tenants, puis lire leurs
    données — sans jamais transmettre de secret par tenant ni redéployer.
    """
    from voyage.models import Route

    _, secret = make_credential()
    subscribe(tenant_a)

    # 1. Découverte : sur quels tenants puis-je travailler ?
    discovery = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)
    assert discovery.status_code == 200
    slugs = [t["slug"] for t in discovery.json()["tenants"]]
    assert slugs == [tenant_a.slug]

    # 2. Lecture des données du tenant découvert.
    routes = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)
    assert routes.status_code == 200
    returned = {row["id"] for row in routes.json()["results"]}
    assert returned == {str(pk) for pk in Route.objects.filter(tenant=tenant_a).values_list("id", flat=True)}

    # 3. Un tenant non abonné reste fermé, avec la même clé.
    assert platform_client(secret, tenant_b.slug).get(
        ROUTES_URL, REMOTE_ADDR=TEST_IP,
    ).status_code == 403

    # 4. L'onboarding du tenant B est un abonnement, rien d'autre.
    subscribe(tenant_b)
    assert platform_client(secret, tenant_b.slug).get(
        ROUTES_URL, REMOTE_ADDR=TEST_IP,
    ).status_code == 200
