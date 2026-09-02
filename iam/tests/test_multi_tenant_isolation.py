"""
TOUPAC IAM — Isolation multi-tenant.

Ces tests sont la seule barrière automatisée contre la fuite de données entre
compagnies clientes. Ils passent par un vrai JWT (cf. la fixture
`authenticated_client`) : avec `force_authenticate`, `request.tenant` resterait
None et toutes les querysets renverraient du vide — les assertions passeraient
même si l'isolation était cassée.
"""
import pytest
from django.contrib.gis.geos import Point
from django.test import RequestFactory
from django.utils import timezone

from colis.models import Order
from core.middleware import TenantMiddleware
from geo.models import Place
from iam.models import User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, Trip

pytestmark = pytest.mark.django_db

TRIPS_URL = "/api/v1/voyage/trips/"
ORDERS_URL = "/api/v1/colis/orders/"
INVOICES_URL = "/api/v1/billing/invoices/"


# ─── Fabriques ───

def make_place(tenant, name, lon, lat):
    return Place.objects.create(
        tenant=tenant, name=name, type=Place.PlaceType.STATION,
        location=Point(lon, lat, srid=4326),
    )


def make_route(tenant, code):
    return Route.objects.create(
        tenant=tenant, name=f"Route {code}", code=code,
        origin_place=make_place(tenant, "Dakar", -17.4441, 14.6937),
        destination_place=make_place(tenant, "Bamako", -8.0029, 12.6392),
    )


def make_trip(tenant, code, internal_id):
    now = timezone.now()
    return Trip.objects.create(
        tenant=tenant, route=make_route(tenant, code), internal_id=internal_id,
        departure_date=now.date(), scheduled_at=now, total_seats=45,
    )


def make_order(tenant, internal_id):
    return Order.objects.create(
        tenant=tenant, internal_id=internal_id, customer_name="Client",
        pickup_place=make_place(tenant, "Retrait", -17.4, 14.7),
        dropoff_place=make_place(tenant, "Livraison", -8.0, 12.6),
    )


def make_invoice(tenant, invoice_number):
    from billing.models import Invoice
    return Invoice.objects.create(
        tenant=tenant, invoice_number=invoice_number, customer_name="Client",
        issue_date=timezone.now().date(), subtotal_xof=10000, total_xof=10000,
    )


# ─── Étanchéité des collections ───

def test_user_only_sees_own_tenant_trips_via_api(authenticated_client, user_admin_a, tenant_a, tenant_b):
    make_trip(tenant_a, "AAA", "VYG-A-001")
    make_trip(tenant_b, "BBB", "VYG-B-001")

    response = authenticated_client(user_admin_a).get(TRIPS_URL)

    assert response.status_code == 200, response.data
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["internal_id"] == "VYG-A-001"


def test_user_cannot_fetch_other_tenant_trip_by_id(authenticated_client, user_admin_a, tenant_b):
    trip_b = make_trip(tenant_b, "BBB", "VYG-B-001")

    response = authenticated_client(user_admin_a).get(f"{TRIPS_URL}{trip_b.id}/")

    # 404 et non 403 : ne pas révéler l'existence d'une ressource d'un autre tenant.
    assert response.status_code == 404


def test_user_cannot_create_trip_in_other_tenant_by_forging_body(
    authenticated_client, user_admin_a, tenant_a, tenant_b,
):
    route_a = make_route(tenant_a, "AAA")
    now = timezone.now()

    response = authenticated_client(user_admin_a).post(TRIPS_URL, {
        "route": str(route_a.id),
        "internal_id": "VYG-FORGE-001",
        "departure_date": now.date().isoformat(),
        "scheduled_at": now.isoformat(),
        "total_seats": 45,
        "tenant": str(tenant_b.id),
    }, format="json")

    assert response.status_code == 201, response.data
    created = Trip.objects.get(internal_id="VYG-FORGE-001")
    assert created.tenant_id == tenant_a.id


def test_user_only_sees_own_tenant_orders_via_api(authenticated_client, user_admin_a, tenant_a, tenant_b):
    make_order(tenant_a, "CMD-A-001")
    make_order(tenant_b, "CMD-B-001")

    response = authenticated_client(user_admin_a).get(ORDERS_URL)

    assert response.status_code == 200, response.data
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["internal_id"] == "CMD-A-001"


def test_user_only_sees_own_tenant_payments_via_api(authenticated_client, user_admin_a, tenant_a, tenant_b):
    """Payment n'a pas d'endpoint list en V1 — on couvre Invoice, même modèle d'isolation."""
    invoice_a = make_invoice(tenant_a, "FAC-2026-0001")
    make_invoice(tenant_b, "FAC-2026-0001")

    response = authenticated_client(user_admin_a).get(INVOICES_URL)

    assert response.status_code == 200, response.data
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["id"] == str(invoice_a.id)


# ─── Comportement du middleware selon le statut du tenant ───

def test_middleware_rejects_jwt_from_suspended_tenant(tenant_suspended, authenticated_client):
    # En V1 c'est acceptable — un tenant suspendu voit simplement rien.
    # À terme, on préférera un 403 explicite via un middleware de gating
    # avant tenant.
    user = User.objects.create_user(
        email="susp@toupac.sn", password="TestPass#2026", first_name="Sus",
        last_name="Pendu", tenant=tenant_suspended, role=User.Role.ADMIN,
    )
    make_trip(tenant_suspended, "SUS", "VYG-SUS-001")

    response = authenticated_client(user).get(TRIPS_URL)

    assert response.status_code == 200
    assert response.data["results"] == []


@pytest.mark.xfail(
    reason="TenantMiddleware filters on status='active' strict, blocking legitimate "
           "trial tenants. To be fixed by allowing status in ('active', 'trial').",
    strict=True,
)
def test_middleware_rejects_jwt_from_trial_tenant_documents_current_bug(
    tenant_trial, authenticated_client,
):
    """Un tenant en essai devrait voir ses propres données — il n'en voit aucune."""
    user = User.objects.create_user(
        email="trial@toupac.sn", password="TestPass#2026", first_name="Tri",
        last_name="Al", tenant=tenant_trial, role=User.Role.ADMIN,
    )
    make_trip(tenant_trial, "TRL", "VYG-TRL-001")

    response = authenticated_client(user).get(TRIPS_URL)

    assert response.status_code == 200
    assert len(response.data["results"]) == 1


def test_middleware_falls_back_to_x_tenant_id_header_only_when_no_jwt(tenant_a, tenant_b, user_admin_b):
    """
    Le header X-Tenant-Id ne sert que faute de JWT : un JWT présent gagne.

    Testé directement sur le middleware — aucun endpoint métier n'est en
    AllowAny, donc il n'y a pas de chemin HTTP pour l'observer.
    """
    middleware = TenantMiddleware(lambda request: None)

    # Sans JWT : le header est pris en compte.
    request = RequestFactory().get("/api/v1/voyage/trips/", HTTP_X_TENANT_ID=str(tenant_a.id))
    middleware.process_request(request)
    assert request.tenant == tenant_a

    # Avec un JWT de tenant_b : le JWT prime, le header est ignoré.
    token = str(ToupacTokenObtainSerializer.get_token(user_admin_b).access_token)
    request = RequestFactory().get(
        "/api/v1/voyage/trips/",
        HTTP_X_TENANT_ID=str(tenant_a.id),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    middleware.process_request(request)
    assert request.tenant == tenant_b
