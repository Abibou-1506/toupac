"""
TOUPAC IAM — Qui a le droit d'ouvrir le centre d'alertes d'un client.

Les mêmes deux voies que le reste de l'espace client : le client par son jeton,
ou un service plateforme agissant pour lui avec le scope dédié. Ces vues
écrivent en plus de lire, ce qui rend la vérification plus sensible qu'ailleurs
— d'où le contrôle sur les cinq points d'entrée, pas seulement sur la liste.
"""
import pytest

from iam.models import User
from iam.tests.customer_factories import make_notification
from iam.tests.platform_helpers import TEST_IP, make_credential, platform_client

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/customer/notifications/"
UNREAD_URL = "/api/v1/customer/notifications/unread-count/"
MARK_ALL_URL = "/api/v1/customer/notifications/mark-all-read/"

READ_SCOPES = ["platform:customer:read", "platform:global:read"]


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def test_a_platform_service_reads_the_alerts_of_the_client_it_acts_for(
    client_fatou, tenant_a,
):
    make_notification(tenant_a, client_fatou, title="Pour Fatou")
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret, acting_email=client_fatou.email).get(
        LIST_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 200
    assert response.json()["notifications"][0]["title"] == "Pour Fatou"


def test_a_platform_service_only_sees_the_client_it_names(
    client_fatou, client_aicha, tenant_a,
):
    """L'en-tête désigne la personne : la clé ne donne pas une vue transverse."""
    make_notification(tenant_a, client_aicha, title="Pour Aïcha")
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret, acting_email=client_fatou.email).get(
        LIST_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.json()["count"] == 0


def test_a_platform_key_without_the_customer_scope_is_refused(client_fatou, tenant_a):
    make_notification(tenant_a, client_fatou)
    _, secret = make_credential(scopes=["platform:voyage:read", "platform:global:read"])

    response = platform_client(secret, acting_email=client_fatou.email).get(
        LIST_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "platform:customer:read" in response.json()["detail"]


def test_a_platform_key_without_an_acting_user_is_refused():
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret).get(LIST_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_a_staff_account_is_refused(authenticated_client, user_dispatcher_a, tenant_a):
    """
    Ces vues ne filtrent par aucune compagnie.

    Les ouvrir au personnel lui donnerait une vue transverse qu'aucun autre
    endpoint ne lui accorde — et le compte du personnel a ses propres alertes,
    qu'un endpoint dédié servira plus tard.
    """
    response = authenticated_client(user_dispatcher_a).get(LIST_URL)

    assert response.status_code == 403


def test_an_anonymous_caller_is_refused(api_client):
    assert api_client.get(LIST_URL).status_code == 401


@pytest.mark.parametrize("url", [LIST_URL, UNREAD_URL, MARK_ALL_URL])
def test_every_collection_endpoint_checks_the_role(
    authenticated_client, user_dispatcher_a, url,
):
    """
    Le contrôle vaut sur les cinq entrées, pas seulement sur la liste.

    « Tout marquer lu » écrit : l'y oublier serait plus grave que sur la liste.
    """
    api = authenticated_client(user_dispatcher_a)
    response = api.post(url) if url == MARK_ALL_URL else api.get(url)

    assert response.status_code == 403


@pytest.mark.parametrize("action", ["read", "ack"])
def test_the_per_alert_endpoints_check_the_role(
    authenticated_client, user_dispatcher_a, client_fatou, tenant_a, action,
):
    notification = make_notification(tenant_a, client_fatou)

    response = authenticated_client(user_dispatcher_a).post(
        f"/api/v1/customer/notifications/{notification.id}/{action}/",
    )

    assert response.status_code == 403
