"""
TOUPAC IAM — Le journal d'audit nomme le client représenté.

Sans cette colonne, la trace dit « le partenaire a lu des réservations chez
Sahel Express » sans dire celles de qui : inexploitable en incident, et
insuffisant pour répondre à un client qui demande qui a consulté ses données.
"""
import pytest

from iam.models import PlatformAuditLog, User
from iam.tests.customer_factories import make_reservation
from iam.tests.platform_helpers import TEST_IP, make_credential, platform_client

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/customer/me/"
RESERVATIONS_URL = "/api/v1/customer/my-reservations/"
TENANTS_URL = "/api/v1/platform/tenants/"
ROUTES_URL = "/api/v1/voyage/routes/"

READ_SCOPES = ["platform:customer:read", "platform:global:read", "platform:voyage:read"]


def test_audit_captures_the_acting_user(client_fatou, tenant_a):
    make_reservation(tenant_a, customer_user=client_fatou)
    credential, secret = make_credential(scopes=READ_SCOPES)

    platform_client(secret, acting_email=client_fatou.email).get(
        RESERVATIONS_URL, REMOTE_ADDR=TEST_IP,
    )

    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    assert log.acting_user_id == client_fatou.id
    assert log.status_code == 200


def test_audit_records_company_and_person_together(client_fatou, tenant_a):
    """« Qui, pour qui, chez quelle compagnie » — les trois dans la même ligne."""
    credential, secret = make_credential(scopes=READ_SCOPES)

    platform_client(secret, tenant_a.slug, acting_email=client_fatou.email).get(
        ROUTES_URL, REMOTE_ADDR=TEST_IP,
    )

    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    assert log.tenant_context_id == tenant_a.id
    assert log.acting_user_id == client_fatou.id


def test_audit_acting_user_is_null_on_global_endpoints():
    """Un endpoint global n'agit pour personne."""
    _, secret = make_credential(scopes=READ_SCOPES)

    platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert PlatformAuditLog.objects.get().acting_user_id is None


def test_audit_acting_user_is_null_for_the_platform_bot(tenant_a):
    """Le porteur technique n'est pas un client : il ne remplit pas la colonne."""
    _, secret = make_credential(scopes=READ_SCOPES)

    platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    log = PlatformAuditLog.objects.get()
    assert log.acting_user_id is None
    assert log.status_code == 200


def test_audit_records_a_refusal_with_its_acting_user(client_fatou):
    """Un accès refusé faute de scope reste attribué à la personne visée."""
    _, secret = make_credential(scopes=["platform:global:read"])

    response = platform_client(secret, acting_email=client_fatou.email).get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    log = PlatformAuditLog.objects.get()
    assert log.acting_user_id == client_fatou.id
    assert log.status_code == 403


def test_audit_distinguishes_two_people_served_by_one_key(client_fatou):
    """La trace sépare les personnes, même derrière une clé unique."""
    aicha, _ = User.get_or_create_client(email="aicha@example.sn")
    _, secret = make_credential(scopes=READ_SCOPES)

    platform_client(secret, acting_email=client_fatou.email).get(ME_URL, REMOTE_ADDR=TEST_IP)
    platform_client(secret, acting_email=aicha.email).get(ME_URL, REMOTE_ADDR=TEST_IP)

    served = set(PlatformAuditLog.objects.values_list("acting_user_id", flat=True))
    assert served == {client_fatou.id, aicha.id}


def test_deleting_a_client_keeps_the_audit_trail(client_fatou):
    """
    `SET_NULL` : effacer un compte ne doit pas effacer la trace des accès.

    Le journal reste la pièce qui permet de dire ce qui a été consulté, même
    après un effacement demandé au titre du RGPD.
    """
    _, secret = make_credential(scopes=READ_SCOPES)
    platform_client(secret, acting_email=client_fatou.email).get(ME_URL, REMOTE_ADDR=TEST_IP)

    client_fatou.delete()

    log = PlatformAuditLog.objects.get()
    assert log.acting_user_id is None
    assert log.status_code == 200
    assert log.endpoint == ME_URL
