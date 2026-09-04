"""
TOUPAC IAM — Rate limiting par clé API.

Les taux réels (1000/h, 10000/h) sont rabaissés ici via override_settings :
émettre 1001 requêtes HTTP rendrait la suite inutilisable, et ce qu'on teste
est le mécanisme de comptage, pas la valeur du quota — laquelle est un
réglage produit, verrouillé séparément par test_configured_rates.
"""
import pytest
from django.contrib.gis.geos import Point
from django.test import override_settings
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import ApiCredential
from voyage.models import Route

pytestmark = pytest.mark.django_db

ROUTES_URL = "/api/v1/voyage/routes/"

AUTH_CLASSES = [
    "iam.api_key_authentication.ApiKeyAuthentication",
    "iam.authentication.DenylistJWTAuthentication",
    "rest_framework.authentication.SessionAuthentication",
]
PERMISSION_CLASSES = [
    "rest_framework.permissions.IsAuthenticated",
    "iam.permissions.HasApiScope",
]


def rest_framework_with(rates):
    """
    Config DRF minimale reprenant la production, hormis les taux.

    Les deux taux sont toujours fournis : DRF instancie chaque throttle
    déclaré sur la vue, et un scope sans taux lève ImproperlyConfigured même
    si ce throttle ne compte pas la requête en cours.
    """
    rates = {"api_key_default": "1000/hour", "api_key_admin": "10000/hour", **rates}
    return {
        "DEFAULT_AUTHENTICATION_CLASSES": AUTH_CLASSES,
        "DEFAULT_PERMISSION_CLASSES": PERMISSION_CLASSES,
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
        "DEFAULT_THROTTLE_RATES": rates,
        "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
        "PAGE_SIZE": 25,
        "EXCEPTION_HANDLER": "core.exceptions.toupac_exception_handler",
    }


def make_route(tenant):
    return Route.objects.create(
        tenant=tenant, name="Route", code="AAA",
        origin_place=Place.objects.create(
            tenant=tenant, name="Origine", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        ),
        destination_place=Place.objects.create(
            tenant=tenant, name="Destination", type=Place.PlaceType.STATION,
            location=Point(-8.0029, 12.6392, srid=4326),
        ),
    )


def key_client(tenant, user, scopes):
    _credential, raw = ApiCredential.issue(
        tenant=tenant, user=user, name="Clé throttle", scopes=scopes,
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)
    return client


def test_configured_rates_are_the_documented_ones(settings):
    """Le portail annonce 1000/h et 10000/h : le réglage doit suivre."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["api_key_default"] == "1000/hour"
    assert rates["api_key_admin"] == "10000/hour"


def test_api_key_throttle_blocks_past_quota(tenant_a, user_admin_a):
    make_route(tenant_a)
    client = key_client(tenant_a, user_admin_a, ["voyage:read"])

    with override_settings(REST_FRAMEWORK=rest_framework_with({"api_key_default": "3/hour"})):
        statuses = [client.get(ROUTES_URL).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


def test_admin_key_uses_its_own_generous_quota(tenant_a, user_admin_a):
    """
    Une clé admin ne doit pas être comptée par le throttle standard.

    DRF applique tous les throttles déclarés — si le standard s'appliquait
    aussi aux clés admin, le quota généreux ne servirait jamais.
    """
    make_route(tenant_a)
    client = key_client(tenant_a, user_admin_a, ["admin:*"])

    with override_settings(REST_FRAMEWORK=rest_framework_with({
        "api_key_default": "1/hour", "api_key_admin": "5/hour",
    })):
        statuses = [client.get(ROUTES_URL).status_code for _ in range(6)]

    assert statuses == [200, 200, 200, 200, 200, 429]


def test_throttles_are_counted_per_key(tenant_a, user_admin_a, user_dispatcher_a):
    """Épuiser une clé n'affecte pas les autres."""
    make_route(tenant_a)
    first = key_client(tenant_a, user_admin_a, ["voyage:read"])
    second = key_client(tenant_a, user_dispatcher_a, ["voyage:read"])

    with override_settings(REST_FRAMEWORK=rest_framework_with({"api_key_default": "1/hour"})):
        assert first.get(ROUTES_URL).status_code == 200
        assert first.get(ROUTES_URL).status_code == 429
        assert second.get(ROUTES_URL).status_code == 200


def test_jwt_user_not_affected_by_api_key_throttle(
    authenticated_client, user_admin_a, tenant_a,
):
    make_route(tenant_a)
    client = authenticated_client(user_admin_a)

    with override_settings(REST_FRAMEWORK=rest_framework_with({"api_key_default": "1/hour"})):
        statuses = [client.get(ROUTES_URL).status_code for _ in range(4)]

    assert statuses == [200] * 4
