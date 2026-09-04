"""
TOUPAC IAM — Authentification par clé API et vérification des scopes.

Deux systèmes d'authentification cohabitent : le JWT pour les humains, la clé
API pour les intégrations tierces. Seule la seconde est cadrée par des scopes ;
ces tests vérifient que la frontière tient dans les deux sens.
"""
import pytest
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import ApiCredential
from voyage.models import Route

pytestmark = pytest.mark.django_db

ROUTES_URL = "/api/v1/voyage/routes/"
ORDERS_URL = "/api/v1/colis/orders/"
VEHICLES_URL = "/api/v1/fleet/vehicles/"


# ─── Fabriques ───

def issue_key(tenant, user, scopes, **kwargs):
    """Crée une clé API et retourne (credential, valeur en clair)."""
    return ApiCredential.issue(tenant=tenant, user=user, name="Clé de test", scopes=scopes, **kwargs)


def key_client(raw_key):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


def make_route(tenant, code="AAA"):
    return Route.objects.create(
        tenant=tenant, name=f"Route {code}", code=code,
        origin_place=Place.objects.create(
            tenant=tenant, name=f"Origine {code}", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        ),
        destination_place=Place.objects.create(
            tenant=tenant, name=f"Destination {code}", type=Place.PlaceType.STATION,
            location=Point(-8.0029, 12.6392, srid=4326),
        ),
    )


# ─── Authentification ───

def test_api_key_authentication_success(tenant_a, user_admin_a):
    make_route(tenant_a)
    _credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client(raw).get(ROUTES_URL)

    assert response.status_code == 200, response.data
    assert response.data["count"] == 1


def test_api_key_authentication_invalid_format(tenant_a, user_admin_a):
    issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client("cle-sans-point").get(ROUTES_URL)

    assert response.status_code == 401
    assert "format" in str(response.data["detail"]).lower()


def test_api_key_authentication_unknown_prefix():
    response = key_client("tpc_00000000.unsecret").get(ROUTES_URL)
    assert response.status_code == 401


def test_api_key_authentication_wrong_secret(tenant_a, user_admin_a):
    credential, _raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client(f"{credential.key_prefix}.mauvais-secret").get(ROUTES_URL)

    assert response.status_code == 401


def test_api_key_authentication_expired_key(tenant_a, user_admin_a):
    _credential, raw = issue_key(
        tenant_a, user_admin_a, ["voyage:read"],
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )

    response = key_client(raw).get(ROUTES_URL)

    assert response.status_code == 401
    assert "expirée" in str(response.data["detail"]).lower()


def test_api_key_authentication_inactive_key(tenant_a, user_admin_a):
    credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])
    credential.is_active = False
    credential.save(update_fields=["is_active"])

    response = key_client(raw).get(ROUTES_URL)

    assert response.status_code == 401


def test_api_key_authentication_updates_last_used_at(tenant_a, user_admin_a):
    credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])
    assert credential.last_used_at is None

    key_client(raw).get(ROUTES_URL)

    credential.refresh_from_db()
    assert credential.last_used_at is not None


def test_api_key_resolves_tenant_for_scoped_querysets(tenant_a, tenant_b, user_admin_a):
    """
    TenantMiddleware ne voit pas la clé API : sans résolution du tenant à
    l'authentification, toutes les listes reviendraient vides.
    """
    make_route(tenant_a, "AAA")
    make_route(tenant_b, "BBB")
    _credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client(raw).get(ROUTES_URL)

    assert response.status_code == 200
    assert [route["code"] for route in response.data["results"]] == ["AAA"]


# ─── has_scope ───

def test_has_scope_returns_true_for_matching_scope(tenant_a, user_admin_a):
    credential, _raw = issue_key(tenant_a, user_admin_a, ["voyage:read", "colis:read"])
    assert credential.has_scope("voyage:read") is True


def test_has_scope_returns_true_for_admin_wildcard(tenant_a, user_admin_a):
    credential, _raw = issue_key(tenant_a, user_admin_a, ["admin:*"])
    assert credential.has_scope("voyage:write") is True
    assert credential.has_scope("billing:read") is True


def test_has_scope_returns_false_for_missing_scope(tenant_a, user_admin_a):
    credential, _raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])
    assert credential.has_scope("voyage:write") is False
    assert credential.has_scope("colis:read") is False


# ─── Application des scopes sur les endpoints ───

def test_endpoint_with_required_scope_accepts_key_with_scope(tenant_a, user_admin_a):
    make_route(tenant_a)
    _credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    assert key_client(raw).get(ROUTES_URL).status_code == 200


def test_endpoint_with_required_scope_rejects_key_without_scope(tenant_a, user_admin_a):
    _credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client(raw).get(ORDERS_URL)

    assert response.status_code == 403
    assert "scope" in str(response.data["detail"]).lower()


def test_endpoint_with_required_scope_accepts_admin_wildcard_key(tenant_a, user_admin_a):
    make_route(tenant_a)
    _credential, raw = issue_key(tenant_a, user_admin_a, ["admin:*"])
    client = key_client(raw)

    assert client.get(ROUTES_URL).status_code == 200
    assert client.get(ORDERS_URL).status_code == 200


def test_write_action_requires_write_scope(tenant_a, user_admin_a):
    """`voyage:read` ne suffit pas pour créer : write n'est pas impliqué par read."""
    route = make_route(tenant_a)
    _credential, raw = issue_key(tenant_a, user_admin_a, ["voyage:read"])

    response = key_client(raw).post(ROUTES_URL, {
        "name": "Nouvelle", "code": "NEW",
        "origin_place": str(route.origin_place_id),
        "destination_place": str(route.destination_place_id),
    }, format="json")

    assert response.status_code == 403


def test_unannotated_endpoint_is_closed_to_api_keys(tenant_a, user_admin_a):
    """
    Défaut fermé : un endpoint qui ne déclare pas de scope refuse les clés API.

    Sans ça, un oubli d'annotation ouvrirait la ressource à toute clé valide.
    """
    _credential, raw = issue_key(tenant_a, user_admin_a, ["admin:*"])

    response = key_client(raw).get(VEHICLES_URL)

    assert response.status_code == 403
    assert "n'est pas exposé" in str(response.data["detail"])


def test_endpoint_with_required_scope_accepts_jwt_user_without_check(
    authenticated_client, user_admin_a, tenant_a,
):
    """Un utilisateur interne en JWT n'est pas soumis aux scopes."""
    make_route(tenant_a)
    client = authenticated_client(user_admin_a)

    assert client.get(ROUTES_URL).status_code == 200
    assert client.get(ORDERS_URL).status_code == 200
    assert client.get(VEHICLES_URL).status_code == 200


# ─── Validation du modèle ───

def test_model_clean_rejects_invalid_scope(tenant_a, user_admin_a):
    credential = ApiCredential(
        tenant=tenant_a, user=user_admin_a, name="Mauvaise clé",
        key_prefix="tpc_bad", key_hash="x", scopes=["voyage:read", "licorne:fly"],
    )

    with pytest.raises(ValidationError) as excinfo:
        credential.clean()

    assert "licorne:fly" in str(excinfo.value)


def test_model_clean_accepts_known_scopes(tenant_a, user_admin_a):
    credential = ApiCredential(
        tenant=tenant_a, user=user_admin_a, name="Bonne clé",
        key_prefix="tpc_good", key_hash="x", scopes=["voyage:read", "admin:*"],
    )
    credential.clean()  # ne lève pas
