"""
TOUPAC Voyage — Graphe de transitions d'état d'un voyage.

Le handler s'appuie sur `ALLOWED_TRANSITIONS`, un graphe codé en dur dans
transitions.py — et non sur les tables du module workflow. C'est une dette
connue, non corrigée ici : ces tests verrouillent le graphe tel qu'il est.

Handler appelé directement (pas via HTTP) : c'est une fonction pure vis-à-vis
du transport, et le passage par le BatchEventProcessor est déjà couvert par
test_batch_session_resolution.py.
"""
import re
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from geo.models import Place
from voyage.models import ControlEvent, Controller, ControlSession, Route, Trip
from voyage.services.exceptions import EventRejected
from voyage.services.handlers.transitions import handle_activity_transition

pytestmark = pytest.mark.django_db

Status = Trip.Status


# ─── Fabriques locales ───

def sample_trip(tenant, status=Status.SCHEDULED, code=None, **extra):
    """Crée Place + Route + Trip dans l'état demandé."""
    code = code or uuid.uuid4().hex[:6].upper()
    route = Route.objects.create(
        tenant=tenant, name=f"Route {code}", code=code,
        origin_place=Place.objects.create(
            tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        ),
        destination_place=Place.objects.create(
            tenant=tenant, name="Bamako", type=Place.PlaceType.STATION,
            location=Point(-8.0029, 12.6392, srid=4326),
        ),
    )
    now = timezone.now()
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id=f"VYG-{code}",
        departure_date=now.date(), scheduled_at=now, total_seats=45,
        status=status, **extra,
    )


def control_session(trip, controller):
    return ControlSession.objects.create(
        tenant=trip.tenant, trip=trip, controller=controller,
        device_id="DEVICE-TEST-01", opened_at=timezone.now(),
    )


def control_event(session, payload, created_at_local=None):
    return ControlEvent.objects.create(
        tenant=session.tenant, session=session, client_uuid=uuid.uuid4(),
        event_type="activity_transition", payload=payload,
        created_at_local=created_at_local or timezone.now(),
    )


@pytest.fixture
def controller_a(user_controller_a):
    return Controller.objects.get(user=user_controller_a)


# ─── Transitions nominales ───

def test_valid_transition_scheduled_to_preparing_is_accepted(tenant_a, controller_a):
    trip = sample_trip(tenant_a, Status.SCHEDULED)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": Status.PREPARING})

    result = handle_activity_transition(event, tenant_a, session)

    assert result["status"] == "accepted"
    trip.refresh_from_db()
    assert trip.status == Status.PREPARING


def test_invalid_transition_scheduled_to_in_transit_is_rejected(tenant_a, controller_a):
    trip = sample_trip(tenant_a, Status.SCHEDULED)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": Status.IN_TRANSIT})

    with pytest.raises(EventRejected, match="Transition interdite"):
        handle_activity_transition(event, tenant_a, session)


def test_transition_to_in_transit_sets_actual_departure_if_missing(tenant_a, controller_a):
    trip = sample_trip(tenant_a, Status.PREPARING)
    session = control_session(trip, controller_a)

    handle_activity_transition(control_event(session, {"to_status": Status.BOARDING}), tenant_a, session)
    departure_event = control_event(session, {"to_status": Status.IN_TRANSIT})
    handle_activity_transition(departure_event, tenant_a, session)

    trip.refresh_from_db()
    assert trip.actual_departure_at == departure_event.created_at_local


def test_transition_to_in_transit_does_not_overwrite_existing_departure_at(tenant_a, controller_a):
    original_departure = timezone.now() - timezone.timedelta(hours=2)
    trip = sample_trip(tenant_a, Status.PREPARING, actual_departure_at=original_departure)
    session = control_session(trip, controller_a)

    handle_activity_transition(control_event(session, {"to_status": Status.BOARDING}), tenant_a, session)
    handle_activity_transition(control_event(session, {"to_status": Status.IN_TRANSIT}), tenant_a, session)

    trip.refresh_from_db()
    assert trip.actual_departure_at == original_departure


# ─── Payloads invalides ───

def test_transition_missing_to_status_is_rejected(tenant_a, controller_a):
    session = control_session(sample_trip(tenant_a), controller_a)
    event = control_event(session, {})

    with pytest.raises(EventRejected, match=re.escape("to_status manquant dans le payload.")):
        handle_activity_transition(event, tenant_a, session)


def test_transition_unknown_to_status_is_rejected(tenant_a, controller_a):
    session = control_session(sample_trip(tenant_a), controller_a)
    event = control_event(session, {"to_status": "pending_alien_invasion"})

    with pytest.raises(EventRejected, match="Statut inconnu"):
        handle_activity_transition(event, tenant_a, session)


# ─── Annulation et états terminaux ───

@pytest.mark.parametrize("from_status", [
    Status.SCHEDULED, Status.PREPARING, Status.BOARDING,
    Status.IN_TRANSIT, Status.AT_STOP, Status.ARRIVING,
])
def test_transition_to_cancelled_is_allowed_from_all_non_terminal_states(
    tenant_a, controller_a, from_status,
):
    trip = sample_trip(tenant_a, from_status)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": Status.CANCELLED})

    result = handle_activity_transition(event, tenant_a, session)

    assert result["status"] == "accepted"
    trip.refresh_from_db()
    assert trip.status == Status.CANCELLED


@pytest.mark.parametrize("terminal_status,to_status", [
    (Status.COMPLETED, Status.IN_TRANSIT),
    (Status.COMPLETED, Status.CANCELLED),
    (Status.CANCELLED, Status.PREPARING),
])
def test_transition_from_terminal_state_is_always_rejected(
    tenant_a, controller_a, terminal_status, to_status,
):
    trip = sample_trip(tenant_a, terminal_status)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": to_status})

    with pytest.raises(EventRejected, match="Transition interdite"):
        handle_activity_transition(event, tenant_a, session)


def test_cycle_at_stop_in_transit_is_allowed(tenant_a, controller_a):
    """Retour en route après une escale — le graphe doit autoriser le cycle."""
    trip = sample_trip(tenant_a, Status.AT_STOP)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": Status.IN_TRANSIT})

    result = handle_activity_transition(event, tenant_a, session)

    assert result["status"] == "accepted"
    trip.refresh_from_db()
    assert trip.status == Status.IN_TRANSIT


# ─── Résolution du trip ciblé ───

def test_transition_uses_session_trip_when_no_trip_id_in_payload(tenant_a, controller_a):
    trip = sample_trip(tenant_a, Status.SCHEDULED)
    session = control_session(trip, controller_a)
    event = control_event(session, {"to_status": Status.PREPARING})

    result = handle_activity_transition(event, tenant_a, session)

    assert result["trip_id"] == str(trip.id)
    trip.refresh_from_db()
    assert trip.status == Status.PREPARING


def test_transition_with_explicit_trip_id_overrides_session_trip(tenant_a, controller_a):
    # TODO sécurité — le handler devrait vérifier que trip.id matche
    # session.trip.id, ou au moins que trip.tenant == session.tenant.
    # En l'état, un contrôleur peut faire transiter n'importe quel voyage de
    # son tenant depuis une session ouverte sur un autre voyage.
    session_trip = sample_trip(tenant_a, Status.SCHEDULED, code="SESS")
    other_trip = sample_trip(tenant_a, Status.SCHEDULED, code="OTHER")
    session = control_session(session_trip, controller_a)
    event = control_event(session, {"to_status": Status.PREPARING, "trip_id": str(other_trip.id)})

    result = handle_activity_transition(event, tenant_a, session)

    assert result["trip_id"] == str(other_trip.id)
    other_trip.refresh_from_db()
    session_trip.refresh_from_db()
    assert other_trip.status == Status.PREPARING
    assert session_trip.status == Status.SCHEDULED
