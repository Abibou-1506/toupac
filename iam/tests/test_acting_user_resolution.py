"""
TOUPAC IAM — Résolution du client représenté par un service plateforme.

Un service plateforme n'agit presque jamais pour lui-même : il traduit la
demande d'une personne. `X-Acting-User-Email` (ou `X-Acting-User-Phone`) désigne
cette personne, qui devient `request.user` pour toute la requête — les vues, les
filtres et la trace d'audit parlent alors du bon compte.
"""
import pytest

from iam.models import PLATFORM_BOT_EMAIL, PlatformAuditLog, User
from iam.tests.platform_helpers import TEST_IP, make_credential, platform_client

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/customer/me/"
TENANTS_URL = "/api/v1/platform/tenants/"


def test_acting_user_email_creates_a_new_client():
    """S'inscrire et être servi sont le même geste pour un passager."""
    _, secret = make_credential()
    assert not User.objects.filter(email="fatou@example.sn").exists()

    response = platform_client(secret, acting_email="fatou@example.sn").get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 200
    created = User.objects.get(email="fatou@example.sn")
    assert created.role == User.Role.CLIENT
    assert created.tenant is None
    assert created.has_usable_password() is False
    assert response.json()["id"] == str(created.id)


def test_acting_user_email_retrieves_an_existing_client(client_fatou):
    _, secret = make_credential()
    before = User.objects.filter(role=User.Role.CLIENT).count()

    response = platform_client(secret, acting_email=client_fatou.email).get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.json()["id"] == str(client_fatou.id)
    assert User.objects.filter(role=User.Role.CLIENT).count() == before


def test_acting_user_phone_is_an_alternative(client_fatou):
    """Le partenaire qui ne connaît qu'un numéro doit pouvoir servir la personne."""
    _, secret = make_credential()

    response = platform_client(secret, acting_phone=client_fatou.phone).get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(client_fatou.id)


def test_email_takes_priority_over_phone():
    """Même règle de résolution que la connexion par code : une seule doctrine."""
    _, secret = make_credential()
    by_email, _ = User.get_or_create_client(email="fatou@example.sn")
    by_phone, _ = User.get_or_create_client(phone="+221770000009")
    assert by_email.pk != by_phone.pk

    response = platform_client(
        secret, acting_email="fatou@example.sn", acting_phone="+221770000009",
    ).get(ME_URL, REMOTE_ADDR=TEST_IP)

    assert response.json()["id"] == str(by_email.id)


def test_acting_user_email_is_normalised():
    _, secret = make_credential()

    platform_client(secret, acting_email="Fatou@Example.SN").get(ME_URL, REMOTE_ADDR=TEST_IP)

    assert User.objects.filter(email="fatou@example.sn").exists()


def test_without_acting_user_the_principal_is_the_platform_bot():
    """Les endpoints globaux n'agissent pour personne : le porteur technique suffit."""
    credential, secret = make_credential()

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200
    log = PlatformAuditLog.objects.get()
    assert log.credential_id == credential.id
    # Le compte technique n'est pas un client : il n'apparaît pas comme représenté.
    assert log.acting_user_id is None
    assert User.objects.filter(email=PLATFORM_BOT_EMAIL).exists()


def test_acting_user_belonging_to_staff_is_refused(user_admin_a):
    """
    Un compte d'exploitation ne se laisse pas endosser.

    Sans ce refus, un partenaire lirait l'espace « client » d'un agent de
    guichet en devinant son adresse professionnelle.
    """
    _, secret = make_credential()

    response = platform_client(secret, acting_email=user_admin_a.email).get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    user_admin_a.refresh_from_db()
    assert user_admin_a.role == User.Role.ADMIN


def test_acting_user_is_ignored_on_global_endpoints():
    """
    Sur un endpoint global, l'en-tête ne change rien.

    `/platform/tenants/` décrit l'intégration, pas une personne : refuser
    l'appel pour un en-tête surnuméraire compliquerait le client sans rien
    protéger. Le principal résolu reste sans effet sur la réponse.
    """
    _, secret = make_credential()

    with_header = platform_client(secret, acting_email="fatou@example.sn").get(
        TENANTS_URL, REMOTE_ADDR=TEST_IP,
    )
    without_header = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert with_header.status_code == 200
    assert with_header.json() == without_header.json()


def test_resolved_client_is_global_and_password_less():
    _, secret = make_credential()

    platform_client(secret, acting_phone="+221771112233").get(ME_URL, REMOTE_ADDR=TEST_IP)

    created = User.objects.get(phone="+221771112233", role=User.Role.CLIENT)
    assert created.tenant is None
    assert created.email is None
    assert created.has_usable_password() is False
