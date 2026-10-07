"""
TOUPAC Billing — `PriceRuleSerializer` expose les noms de route et de zone.

La page détail /tarifs/{uuid} du backoffice affichait des UUIDs tronqués pour
`route`, `origin_zone` et `destination_zone` : l'enrichissement par 4 champs
nested source=... remplace ces UUIDs par des noms lisibles tout en gardant
les UUIDs d'origine (champs additifs, non-breaking pour les apps RN).

Le ViewSet `PriceListViewSet` est également testé pour l'invariance N+1
quand une grille contient N règles route-based.
"""
import pytest
from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from billing.models import PriceList, PriceRule
from billing.serializers import PriceRuleSerializer
from geo.models import Place, Zone
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Tarif", slug="tarif-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.tarif@toupac.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def price_list(tenant):
    return PriceList.objects.create(
        tenant=tenant, name="Grille Voyage 2026", type=PriceList.Type.VOYAGE,
    )


def _place(tenant, name, lon, lat):
    return Place.objects.create(
        tenant=tenant, name=name, type=Place.PlaceType.STATION,
        location=Point(lon, lat, srid=4326),
    )


def _square(lon, lat, d=0.01):
    """Petit carré autour de (lon, lat) pour la PolygonField geography."""
    ring = [
        (lon - d, lat - d), (lon + d, lat - d),
        (lon + d, lat + d), (lon - d, lat + d),
        (lon - d, lat - d),
    ]
    return Polygon(ring, srid=4326)


def _zone(tenant, name, lon=-17.44, lat=14.69):
    return Zone.objects.create(
        tenant=tenant, name=name, type=Zone.ZoneType.TARIFF,
        boundary=_square(lon, lat),
    )


# ─── Tests unitaires du serializer ───

def test_price_rule_serializer_exposes_route_name_and_code(tenant, price_list):
    """route_name et route_code resolvent les champs du FK Route."""
    origin = _place(tenant, "Dakar", -17.44, 14.69)
    destination = _place(tenant, "Bamako", -8.00, 12.64)
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code="DKR-BKO",
        origin_place=origin, destination_place=destination,
    )
    rule = PriceRule.objects.create(
        tenant=tenant, price_list=price_list, route=route,
        base_amount_xof=15000,
    )

    data = PriceRuleSerializer(rule).data

    assert data["route_name"] == "Dakar → Bamako"
    assert data["route_code"] == "DKR-BKO"
    # Non-breaking : l'UUID d'origine reste exposé (sous forme UUID à ce stade,
    # stringifié par la couche JSON lors du rendu HTTP).
    assert str(data["route"]) == str(route.id)


def test_price_rule_serializer_route_fields_are_null_when_route_is_null(
    tenant, price_list,
):
    """route_name / route_code sont None quand la FK route est null."""
    rule = PriceRule.objects.create(
        tenant=tenant, price_list=price_list, route=None,
        base_amount_xof=5000,
    )

    data = PriceRuleSerializer(rule).data

    assert data["route"] is None
    assert data["route_name"] is None
    assert data["route_code"] is None


def test_price_rule_serializer_exposes_zone_names(tenant, price_list):
    """origin_zone_name / destination_zone_name resolvent le FK Zone.name."""
    zone_nord = _zone(tenant, "Nord", lon=-17.44, lat=15.5)
    zone_sud = _zone(tenant, "Sud", lon=-17.44, lat=13.5)
    rule = PriceRule.objects.create(
        tenant=tenant, price_list=price_list,
        origin_zone=zone_nord, destination_zone=zone_sud,
        base_amount_xof=7500,
        calculation_method=PriceRule.CalculationMethod.PER_ZONE,
    )

    data = PriceRuleSerializer(rule).data

    assert data["origin_zone_name"] == "Nord"
    assert data["destination_zone_name"] == "Sud"
    assert str(data["origin_zone"]) == str(zone_nord.id)
    assert str(data["destination_zone"]) == str(zone_sud.id)


# ─── Tests end-to-end via le ViewSet ───

def test_price_list_viewset_detail_exposes_enriched_rules(
    admin_client, tenant, price_list,
):
    """GET /price-lists/{id}/ propage les 4 nouveaux champs à chaque rule."""
    origin = _place(tenant, "Dakar", -17.44, 14.69)
    destination = _place(tenant, "Bamako", -8.00, 12.64)
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code="DKR-BKO",
        origin_place=origin, destination_place=destination,
    )
    zone_nord = _zone(tenant, "Nord", lon=-17.44, lat=15.5)
    zone_sud = _zone(tenant, "Sud", lon=-17.44, lat=13.5)
    PriceRule.objects.create(
        tenant=tenant, price_list=price_list, route=route,
        base_amount_xof=15000,
    )
    PriceRule.objects.create(
        tenant=tenant, price_list=price_list,
        origin_zone=zone_nord, destination_zone=zone_sud,
        base_amount_xof=7500,
        calculation_method=PriceRule.CalculationMethod.PER_ZONE,
    )

    response = admin_client.get(f"/api/v1/billing/price-lists/{price_list.id}/")

    assert response.status_code == 200
    rules = response.data["rules"]
    assert len(rules) == 2
    for rule in rules:
        assert "route_name" in rule
        assert "route_code" in rule
        assert "origin_zone_name" in rule
        assert "destination_zone_name" in rule

    route_rule = next(r for r in rules if r["route"] is not None)
    zone_rule = next(r for r in rules if r["origin_zone"] is not None)
    assert route_rule["route_name"] == "Dakar → Bamako"
    assert route_rule["route_code"] == "DKR-BKO"
    assert zone_rule["origin_zone_name"] == "Nord"
    assert zone_rule["destination_zone_name"] == "Sud"


def test_price_list_viewset_detail_uses_prefetch_to_avoid_n_plus_1(
    admin_client, tenant, price_list,
):
    """Avec N règles route-based, le nombre de queries ne scale pas linéairement.

    L'invariant qui compte : le total reste borné (prefetch_related sur
    rules + rules__route + zones). On fige un seuil large (<= 10) qui
    reste honoré même si Django ajoute une query de session/tenant.
    """
    origin = _place(tenant, "Dakar", -17.44, 14.69)
    destination = _place(tenant, "Bamako", -8.00, 12.64)
    for i in range(5):
        route = Route.objects.create(
            tenant=tenant, name=f"Route {i}", code=f"R-{i:03d}",
            origin_place=origin, destination_place=destination,
        )
        PriceRule.objects.create(
            tenant=tenant, price_list=price_list, route=route,
            base_amount_xof=10000 + i,
        )

    with CaptureQueriesContext(connection) as ctx:
        response = admin_client.get(f"/api/v1/billing/price-lists/{price_list.id}/")

    assert response.status_code == 200
    assert len(response.data["rules"]) == 5
    assert len(ctx.captured_queries) <= 10, (
        f"Attendu <= 10 queries, obtenu {len(ctx.captured_queries)} — "
        "le prefetch sur rules__route a probablement regressé."
    )
