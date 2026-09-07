"""
TOUPAC IAM — Espace client atteint par un service plateforme.

Deux voies mènent aux endpoints `/customer/*` : le client par son jeton, ou un
partenaire agissant pour lui. La seconde exige un scope dédié
(`platform:customer:read`) en plus du client désigné — sans quoi n'importe
quelle clé plateforme lirait l'espace de n'importe qui en ajoutant un en-tête.
"""
import pytest

from iam.models import User
from iam.tests.customer_factories import make_order, make_reservation
from iam.tests.platform_helpers import TEST_IP, make_credential, platform_client

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/customer/me/"
RESERVATIONS_URL = "/api/v1/customer/my-reservations/"
ORDERS_URL = "/api/v1/customer/my-orders/"

READ_SCOPES = ["platform:customer:read", "platform:global:read"]


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def test_my_reservations_via_platform_and_acting_user(client_fatou, tenant_a):
    make_reservation(tenant_a, customer_user=client_fatou)
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret, acting_email=client_fatou.email).get(
        RESERVATIONS_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 200
    assert len(response.json()["reservations"]) == 1


def test_my_orders_via_platform_and_acting_user(client_fatou, tenant_a):
    make_order(tenant_a, customer=client_fatou)
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret, acting_email=client_fatou.email).get(
        ORDERS_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 200
    assert len(response.json()["orders"]) == 1


def test_without_the_customer_scope_it_is_refused(client_fatou, tenant_a):
    """Le client désigné ne suffit pas : la clé doit porter le scope."""
    make_reservation(tenant_a, customer_user=client_fatou)
    _, secret = make_credential(scopes=["platform:voyage:read", "platform:global:read"])

    response = platform_client(secret, acting_email=client_fatou.email).get(
        RESERVATIONS_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "platform:customer:read" in response.json()["detail"]


def test_without_the_acting_user_header_it_is_refused():
    """
    Le scope ne suffit pas non plus : il faut savoir de qui l'on parle.

    Le message doit nommer l'en-tête manquant — sinon l'intégrateur cherche un
    scope absent alors que c'est la personne qui manque.
    """
    _, secret = make_credential(scopes=READ_SCOPES)

    response = platform_client(secret).get(RESERVATIONS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
    assert "X-Acting-User-Email" in response.json()["detail"]


def test_isolation_between_acting_users(client_fatou, client_aicha, tenant_a):
    """
    Le même partenaire, deux personnes, deux réponses disjointes.

    C'est l'isolation qui compte le plus ici : une clé unique sert tout le monde,
    et rien ne doit fuir d'un compte à l'autre.
    """
    mine = make_reservation(tenant_a, customer_user=client_fatou)
    hers = make_reservation(tenant_a, customer_user=client_aicha)
    _, secret = make_credential(scopes=READ_SCOPES)

    fatou_items = platform_client(secret, acting_email=client_fatou.email).get(
        RESERVATIONS_URL, REMOTE_ADDR=TEST_IP,
    ).json()["reservations"]
    aicha_items = platform_client(secret, acting_email=client_aicha.email).get(
        RESERVATIONS_URL, REMOTE_ADDR=TEST_IP,
    ).json()["reservations"]

    assert [item["id"] for item in fatou_items] == [str(mine.id)]
    assert [item["id"] for item in aicha_items] == [str(hers.id)]


def test_jwt_access_still_works_without_any_platform_scope(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Le client connecté n'a que faire des scopes plateforme.

    Ils n'existent que pour encadrer un tiers agissant en son nom ; les exiger
    de lui casserait l'application cliente.
    """
    make_reservation(tenant_a, customer_user=client_fatou)

    response = authenticated_client(client_fatou).get(RESERVATIONS_URL)

    assert response.status_code == 200
    assert len(response.json()["reservations"]) == 1


def test_staff_jwt_is_still_refused(authenticated_client, user_admin_a):
    """L'ouverture aux partenaires n'ouvre rien au personnel des compagnies."""
    assert authenticated_client(user_admin_a).get(RESERVATIONS_URL).status_code == 403


def test_customer_me_via_platform_returns_the_acting_user(client_fatou):
    _, secret = make_credential(scopes=READ_SCOPES)

    body = platform_client(secret, acting_email=client_fatou.email).get(
        ME_URL, REMOTE_ADDR=TEST_IP,
    ).json()

    assert body["id"] == str(client_fatou.id)
    assert body["email"] == client_fatou.email


def test_acting_customer_throttle_is_per_person(settings, client_fatou, client_aicha):
    """
    Le plafond par personne borne ce qu'un partenaire peut extraire d'un compte.

    Le taux est abaissé pour le test : ce qui est vérifié est le mécanisme —
    le compteur porte sur le client représenté, pas sur la clé — et non la
    valeur de production.
    """
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "acting_customer": "2/hour",
        },
    }
    _, secret = make_credential(scopes=READ_SCOPES)
    fatou = platform_client(secret, acting_email=client_fatou.email)

    assert fatou.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 200
    assert fatou.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 200
    assert fatou.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 429

    # Le compteur d'une personne n'affecte pas celui d'une autre.
    aicha = platform_client(secret, acting_email=client_aicha.email)
    assert aicha.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 200


def test_platform_key_throttle_still_applies(settings, client_fatou):
    """Les deux compteurs se cumulent : le plafond par clé reste opposable."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "platform_key_default": "1/hour",
            "acting_customer": "1000/hour",
        },
    }
    _, secret = make_credential(scopes=READ_SCOPES)
    caller = platform_client(secret, acting_email=client_fatou.email)

    assert caller.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 200
    assert caller.get(ME_URL, REMOTE_ADDR=TEST_IP).status_code == 429


def test_jwt_client_is_not_subject_to_platform_throttles(settings, authenticated_client, client_fatou):
    """Les deux compteurs ne comptent rien hors requête plateforme."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "acting_customer": "1/hour",
            "platform_key_default": "1/hour",
        },
    }
    client = authenticated_client(client_fatou)

    for _ in range(3):
        assert client.get(ME_URL).status_code == 200
