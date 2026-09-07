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
)

pytestmark = pytest.mark.django_db

TENANTS_URL = "/api/v1/platform/tenants/"
HEALTH_URL = "/api/v1/platform/health/"
NOTIFICATIONS_URL = "/api/v1/platform/notifications/"
ROUTES_URL = "/api/v1/voyage/routes/"


# ─── Endpoints globaux ───

def test_platform_tenants_lists_every_active_company(tenant_a, tenant_b, tenant_trial):
    """
    Aucune habilitation préalable : toute compagnie active est accessible.

    C'est le cœur du correctif d'USR-4 — un service plateforme est une
    fonctionnalité de TOUPAC, pas une option à souscrire compagnie par compagnie.
    """
    _, secret = make_credential()

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    slugs = {t["slug"] for t in response.json()["tenants"]}
    assert {tenant_a.slug, tenant_b.slug, tenant_trial.slug} <= slugs


def test_platform_tenants_excludes_suspended_companies(tenant_a, tenant_suspended):
    """Annoncer une compagnie suspendue promettrait un service qui refusera les appels."""
    _, secret = make_credential()

    slugs = {
        t["slug"] for t in
        platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP).json()["tenants"]
    }

    assert tenant_a.slug in slugs
    assert tenant_suspended.slug not in slugs


def test_platform_health_reports_no_expiry_by_default():
    """Le cas nominal depuis USR-4 : une clé vit jusqu'à sa révocation."""
    credential, secret = make_credential(scopes=["platform:global:read"])

    response = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    body = response.json()
    assert body["platform_service"] == credential.platform_service
    assert body["scopes"] == ["platform:global:read"]
    assert body["expires_at"] is None
    assert body["days_until_expiry"] is None


def test_platform_health_reports_expiry_when_set():
    from datetime import timedelta

    from django.utils import timezone

    _, secret = make_credential(
        scopes=["platform:global:read"], expires_at=timezone.now() + timedelta(days=90),
    )

    body = platform_client(secret).get(HEALTH_URL, REMOTE_ADDR=TEST_IP).json()

    assert body["expires_at"] is not None
    assert 89 <= body["days_until_expiry"] <= 90


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

    response = platform_client(secret, tenant_a.slug).get(NOTIFICATIONS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Pour A"]


# ─── Journal d'audit ───

def test_audit_log_created_on_each_call(tenant_a):
    credential, secret = make_credential()

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


def test_audit_log_created_on_unknown_company(tenant_a):
    """« A visé une compagnie qui n'existe pas » doit rester visible."""
    _, secret = make_credential()

    response = platform_client(secret, "compagnie-fantome").get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

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
    Le parcours complet promis à l'équipe partenaire.

    Une clé, aucune démarche par compagnie : découvrir les compagnies, lire
    celles qu'on veut, sans redéployer ni transmettre de secret supplémentaire.
    """
    from voyage.models import Route

    _, secret = make_credential()

    # 1. Découverte : quelles compagnies puis-je servir ?
    discovery = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)
    assert discovery.status_code == 200
    slugs = {t["slug"] for t in discovery.json()["tenants"]}
    assert {tenant_a.slug, tenant_b.slug} <= slugs

    # 2. Lecture des données d'une compagnie découverte.
    routes = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)
    assert routes.status_code == 200
    returned = {row["id"] for row in routes.json()["results"]}
    assert returned == {
        str(pk) for pk in Route.objects.filter(tenant=tenant_a).values_list("id", flat=True)
    }

    # 3. La compagnie suivante s'atteint avec la même clé, sans étape préalable.
    other = platform_client(secret, tenant_b.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)
    assert other.status_code == 200
    other_ids = {row["id"] for row in other.json()["results"]}
    # Le cloisonnement tient malgré tout : chaque appel ne rend qu'une compagnie.
    assert returned & other_ids == set()
