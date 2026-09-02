"""
TOUPAC IAM — Authentification JWT : login, throttle, /me/, logout, refresh.

Les claims custom (`tenant_id`, `role`, `name`) portés par le token access
sont lus par TenantMiddleware avant toute authentification DRF : s'ils
disparaissaient, la résolution du tenant tomberait silencieusement.
"""
import jwt
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from conftest import PASSWORD

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"


def decode_unverified(token):
    """Lit les claims sans vérifier la signature — on teste le contenu, pas la crypto."""
    return jwt.decode(token, options={"verify_signature": False})


def login(client, email, password=PASSWORD):
    return client.post(LOGIN_URL, {"email": email, "password": password}, format="json")


def test_login_returns_access_and_refresh_tokens_with_valid_credentials(api_client, user_admin_a):
    response = login(api_client, user_admin_a.email)

    assert response.status_code == 200, response.data
    assert "access" in response.data
    assert "refresh" in response.data

    claims = decode_unverified(response.data["access"])
    assert claims["tenant_id"] == str(user_admin_a.tenant_id)
    assert claims["role"] == user_admin_a.role
    assert claims["name"] == user_admin_a.full_name


def test_login_rejects_wrong_password(api_client, user_admin_a):
    response = login(api_client, user_admin_a.email, password="WrongPass#0000")
    assert response.status_code == 401


def test_login_rejects_unknown_email(api_client):
    response = login(api_client, "personne@nulle-part.sn")
    assert response.status_code == 401


def test_login_throttle_after_10_attempts_per_minute(api_client, user_admin_a):
    # Taux verrouillé ici : si quelqu'un change auth_login dans les settings,
    # ce test doit rester le contrat, pas suivre silencieusement.
    rates = {"auth_login": "10/minute", "batch_sync": "20/minute",
             "payment_initiate": "30/minute", "tenant_burst": "100/minute"}
    with override_settings(REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
        "DEFAULT_THROTTLE_RATES": rates,
    }):
        statuses = [
            login(api_client, user_admin_a.email, password="WrongPass#0000").status_code
            for _ in range(11)
        ]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


def test_me_endpoint_returns_current_user_profile(authenticated_client, user_admin_a):
    response = authenticated_client(user_admin_a).get(ME_URL)

    assert response.status_code == 200, response.data
    assert response.data["email"] == user_admin_a.email
    assert response.data["role"] == user_admin_a.role
    assert response.data["tenant_id"] == user_admin_a.tenant_id
    assert response.data["tenant_name"] == "Compagnie A"


def test_me_endpoint_requires_authentication(api_client):
    assert api_client.get(ME_URL).status_code == 401


def test_logout_blacklists_refresh_token(api_client, user_admin_a, authenticated_client):
    tokens = login(api_client, user_admin_a.email).data
    client = authenticated_client(user_admin_a)

    logout = client.post(LOGOUT_URL, {"refresh": tokens["refresh"]}, format="json")
    assert logout.status_code == 200, logout.data

    replay = APIClient().post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json")
    assert replay.status_code == 401


def test_logout_returns_200_even_without_refresh_body(authenticated_client, user_admin_a):
    """Verrouille le comportement actuel : sans `refresh`, le logout est un no-op à 200."""
    response = authenticated_client(user_admin_a).post(LOGOUT_URL, {}, format="json")
    assert response.status_code == 200
    assert response.data["detail"] == "Déconnexion réussie."


def test_logout_returns_400_on_malformed_refresh_token(authenticated_client, user_admin_a):
    response = authenticated_client(user_admin_a).post(
        LOGOUT_URL, {"refresh": "not-a-jwt"}, format="json",
    )
    assert response.status_code == 400


@pytest.mark.xfail(
    reason="Access token denylist not yet implemented — see Sprint 2 §4.19, "
           "only refresh is blacklisted in V1",
    strict=True,
)
def test_access_token_still_valid_after_logout(api_client, user_admin_a):
    """Le logout ne révoque que le refresh : l'access reste utilisable jusqu'à son exp."""
    tokens = login(api_client, user_admin_a.email).data

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    client.post(LOGOUT_URL, {"refresh": tokens["refresh"]}, format="json")

    assert client.get(ME_URL).status_code == 401
