"""
TOUPAC Voyage — Endpoint `GET /api/v1/voyage/control-events/{client_uuid}/`.

Lookup direct par `client_uuid` pour la réconciliation mobile après crash
ou timeout. Scope strict contrôleur, serializer en liste blanche explicite.

Cas couverts :
- 200 sur event accepted / rejected du contrôleur authentifié
- 404 sur client_uuid inconnu
- 404 cross-tenant (le controleur de B ne voit pas l'event de A)
- 404 cross-contrôleur même tenant (A ne voit pas l'event de B)
- 403 si user sans controller_profile
- 401 si non authentifié
- Serializer en liste blanche stricte : exactement 8 clés, aucun champ
  interdit exposé (payload, gps_*, target_*, tenant)
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import (
    Controller,
    ControlSession,
    Reservation,
    Route,
    RouteStop,
    SeatMap,
    Trip,
)
from voyage.services.event_processor import BatchEventProcessor
from voyage.services.exceptions import RejectionCode

pytestmark = pytest.mark.django_db


# ─── Fixtures locales : pas de dépendance au conftest batch_hardening ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Lookup Co", slug="lookup-co")


@pytest.fixture
def tenant_other():
    return Tenant.objects.create(name="Rival Co", slug="rival-co")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@lookup-co.sn", password="TestPass#2026",
        first_name="Awa", last_name="Fall",
        tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-700")


@pytest.fixture
def controller_other(tenant):
    """Deuxième contrôleur du même tenant, pour tester l'isolation."""
    user = User.objects.create_user(
        email="ctrl2@lookup-co.sn", password="TestPass#2026",
        first_name="Modou", last_name="Diouf",
        tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-701")


@pytest.fixture
def controller_cross_tenant(tenant_other):
    user = User.objects.create_user(
        email="ctrl@rival-co.sn", password="TestPass#2026",
        first_name="Jean", last_name="Dupuis",
        tenant=tenant_other, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(
        tenant=tenant_other, user=user, matricule="CH-RIVAL-01",
    )


def _build_trip(tenant):
    origin = Place.objects.create(
        tenant=tenant, name=f"Dakar {tenant.slug}", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name=f"Bamako {tenant.slug}", type=Place.PlaceType.STATION,
        location=Point(-8.0029, 12.6392, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="DKR → BKO", code=f"DKR-BKO-{tenant.slug[:3]}",
        origin_place=origin, destination_place=destination,
    )
    for order_, place in enumerate([origin, destination]):
        RouteStop.objects.create(
            tenant=tenant, route=route, place=place, stop_order=order_,
        )
    seat_map = SeatMap.objects.create(
        tenant=tenant, name=f"Plan {tenant.slug}", total_seats=6,
        layout={"rows": 2, "cols": 3},
    )
    return Trip.objects.create(
        tenant=tenant, route=route,
        internal_id=f"T-LOOKUP-{tenant.slug[:3].upper()}",
        departure_date=timezone.now().date(),
        scheduled_at=timezone.now(),
        total_seats=6, seat_map=seat_map, status=Trip.Status.BOARDING,
    )


@pytest.fixture
def trip(tenant):
    return _build_trip(tenant)


@pytest.fixture
def trip_other_tenant(tenant_other):
    return _build_trip(tenant_other)


@pytest.fixture
def session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="DEVICE-700", opened_at=timezone.now(),
    )


@pytest.fixture
def session_other_controller(tenant, controller_other, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller_other,
        device_id="DEVICE-701", opened_at=timezone.now(),
    )


@pytest.fixture
def session_cross_tenant(tenant_other, controller_cross_tenant, trip_other_tenant):
    return ControlSession.objects.create(
        tenant=tenant_other, trip=trip_other_tenant,
        controller=controller_cross_tenant,
        device_id="DEVICE-RIVAL-01", opened_at=timezone.now(),
    )


def _authed_client(user):
    """Client DRF avec JWT auth réel (passe par TenantMiddleware)."""
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _emit_sale(session, tenant, trip, seat_label="A1"):
    """Émet un event onboard_sale et renvoie son client_uuid + verdict."""
    processor = BatchEventProcessor(
        session=session, tenant=tenant, user=session.controller.user,
    )
    client_uuid = str(uuid.uuid4())
    stops = list(trip.route.stops.order_by("stop_order"))
    verdict = processor.process_batch([{
        "client_uuid": client_uuid,
        "event_type": "onboard_sale",
        "payload": {
            "seat_label": seat_label,
            "amount_xof": 10000,
            "passenger_data": {
                "first_name": "Fatou", "last_name": "Mbaye",
                "phone": "+221770001234",
            },
            "origin_stop": str(stops[0].pk),
            "destination_stop": str(stops[-1].pk),
        },
        "created_at_local": timezone.now().isoformat(),
    }])[0]
    return client_uuid, verdict


# ─── 1. 200 sur event accepted ───

def test_lookup_returns_200_for_accepted_event(session, tenant, trip, controller):
    client_uuid, verdict = _emit_sale(session, tenant, trip)
    assert verdict["status"] == "accepted"

    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert response.status_code == 200, response.data
    assert str(response.data["client_uuid"]) == client_uuid
    assert response.data["event_type"] == "onboard_sale"
    assert response.data["status"] == "processed"
    assert response.data["rejection_code"] == ""
    assert response.data["processed_at"] is not None


# ─── 2. 200 sur event rejected ───

def test_lookup_returns_200_for_rejected_event(
    session, tenant, trip, controller,
):
    # Occupe A1 pour qu'une vente sur A1 soit rejetée en SEAT_ALREADY_TAKEN.
    from voyage.models import Passenger
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Occupy", last_name="A1", phone="+221770009999",
    )
    Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger, seat_label="A1",
        status=Reservation.Status.BOOKED, amount_xof=10000,
    )

    client_uuid, verdict = _emit_sale(session, tenant, trip, seat_label="A1")
    assert verdict["status"] == "rejected"
    assert verdict["rejection_code"] == RejectionCode.SEAT_ALREADY_TAKEN

    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert response.status_code == 200
    assert response.data["status"] == "rejected"
    assert response.data["rejection_code"] == RejectionCode.SEAT_ALREADY_TAKEN
    assert response.data["rejection_reason"]  # non vide


# ─── 3. 404 sur client_uuid inconnu ───

def test_lookup_returns_404_for_unknown_client_uuid(controller):
    random_uuid = uuid.uuid4()
    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{random_uuid}/",
    )
    assert response.status_code == 404
    assert response.data == {"detail": "Événement introuvable."}


# ─── 4. 404 cross-tenant ───

def test_lookup_returns_404_cross_tenant(
    session_cross_tenant, tenant_other, trip_other_tenant, controller,
):
    """Un event du tenant B ne doit pas être visible par un contrôleur du
    tenant A — attendre 404 (pas 403, pas 200)."""
    client_uuid, _ = _emit_sale(
        session_cross_tenant, tenant_other, trip_other_tenant,
    )
    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert response.status_code == 404


# ─── 5. 404 cross-contrôleur même tenant ───

def test_lookup_returns_404_cross_controller_same_tenant(
    session_other_controller, tenant, trip, controller,
):
    """Un event du contrôleur B n'est pas visible par le contrôleur A du
    même tenant — attendre 404 (doctrine : ressource nominative non
    détenue → 404, jamais 403)."""
    client_uuid, _ = _emit_sale(session_other_controller, tenant, trip)
    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert response.status_code == 404


# ─── 6. 403 si user sans controller_profile ───

def test_lookup_returns_403_for_non_controller(tenant):
    admin = User.objects.create_user(
        email="admin@lookup-co.sn", password="TestPass#2026",
        first_name="Ad", last_name="Min",
        tenant=tenant, role=User.Role.ADMIN,
    )
    response = _authed_client(admin).get(
        f"/api/v1/voyage/control-events/{uuid.uuid4()}/",
    )
    assert response.status_code == 403
    assert response.data == {"detail": "Utilisateur non contrôleur."}


# ─── 7. 401 si non authentifié ───

def test_lookup_returns_401_without_auth():
    response = APIClient().get(
        f"/api/v1/voyage/control-events/{uuid.uuid4()}/",
    )
    assert response.status_code == 401


# ─── 8. Serializer en liste blanche stricte ───

def test_lookup_response_has_exactly_the_8_whitelisted_fields(
    session, tenant, trip, controller,
):
    client_uuid, _ = _emit_sale(session, tenant, trip)
    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert response.status_code == 200

    expected = {
        "client_uuid",
        "event_type",
        "status",
        "rejection_code",
        "rejection_reason",
        "processed_at",
        "created_at_local",
        "session_id",
    }
    assert set(response.data.keys()) == expected, (
        f"Clés inattendues : {set(response.data.keys()) ^ expected}"
    )

    # Double garde explicite : les champs sensibles doivent être absents.
    forbidden = {
        "payload",
        "target_type",
        "target_id",
        "gps_location",
        "gps_accuracy_m",
        "tenant",
    }
    assert not (set(response.data.keys()) & forbidden), (
        f"Champs sensibles fuités : {set(response.data.keys()) & forbidden}"
    )


# ─── 9. session_id correctement nested ───

def test_lookup_response_exposes_session_id_from_nested_source(
    session, tenant, trip, controller,
):
    """`session_id` est dérivé via `source="session.id"` pour éviter un
    second roundtrip côté mobile."""
    client_uuid, _ = _emit_sale(session, tenant, trip)
    response = _authed_client(controller.user).get(
        f"/api/v1/voyage/control-events/{client_uuid}/",
    )
    assert str(response.data["session_id"]) == str(session.id)
