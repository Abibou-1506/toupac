"""
TOUPAC Voyage — Fin de vie d'un voyage : arrivée réelle et résumé agrégé.

Deux trous historiques se croisent ici :

- `actual_arrival_at` restait `None` quand le voyage était clos depuis la
  chaîne batch offline, parce que `handle_activity_transition` ne touchait pas
  à ce champ. Côté vue de clôture `trips/<id>/control/close/`, il était bien
  renseigné — avec `timezone.now()`. Les stats de ponctualité à l'arrivée
  étaient donc fausses pour tout voyage passé par le batch, correctes pour les
  autres.
- `Trip.summary` existait depuis le port Sprint 2 et n'était jamais rempli.

Les deux sont corrigés dans le même ticket parce qu'ils vivent à la même
frontière temporelle — la fermeture du voyage — et qu'un correctif isolé
aurait laissé l'autre défaut en évidence.
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.db import DatabaseError
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import (
    CashEntry,
    Controller,
    ControlSession,
    Passenger,
    Reservation,
    Route,
    Trip,
)
from voyage.services.event_processor import BatchEventProcessor
from voyage.services.trip_summary import build_trip_summary

pytestmark = pytest.mark.django_db


# ─── Décor minimal ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Fin", slug="fin-trip")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@fin-trip.sn", password="TestPass#2026",
        first_name="Moussa", last_name="Sarr",
        tenant=tenant, role=User.Role.CONTROLLER, is_staff=True,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-F01")


@pytest.fixture
def route(tenant):
    place = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    other = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.9246, 14.7886, srid=4326),
    )
    return Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS",
        origin_place=place, destination_place=other,
    )


@pytest.fixture
def trip(tenant, route):
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-F01",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45, status=Trip.Status.ARRIVING,
    )


@pytest.fixture
def session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="DEVICE-F01", opened_at=timezone.now(),
    )


# ─── Bloc 3 — `actual_arrival_at` sur `arriving → completed` ───

def _transition_event(to_status):
    return {
        "client_uuid": str(uuid.uuid4()),
        "event_type": "activity_transition",
        "payload": {"to_status": to_status},
        "created_at_local": timezone.now().isoformat(),
    }


def test_arriving_to_completed_sets_actual_arrival_at(session, tenant, controller, trip):
    """Trou historique corrigé : les stats de ponctualité tenaient à cette ligne."""
    assert trip.actual_arrival_at is None

    event = _transition_event("completed")
    BatchEventProcessor(session=session, tenant=tenant, user=controller.user).process_batch([event])

    trip.refresh_from_db()
    assert trip.actual_arrival_at is not None
    # L'horodatage du device est préféré à `timezone.now()` serveur : c'est le
    # bon moment pour la ponctualité (quand le contrôleur a pressé le bouton,
    # pas quand le serveur a reçu le batch).
    assert trip.actual_arrival_at.isoformat()[:10] == timezone.now().isoformat()[:10]


def test_an_existing_arrival_time_is_preserved(session, tenant, controller, trip):
    """
    Miroir de `actual_departure_at` : si un chemin l'a déjà posé, le batch ne
    l'écrase pas. Cela protège contre un batch rejoué après la vue de clôture.
    """
    import datetime

    earlier = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)
    trip.actual_arrival_at = earlier
    trip.save(update_fields=["actual_arrival_at"])

    BatchEventProcessor(session=session, tenant=tenant, user=controller.user).process_batch(
        [_transition_event("completed")],
    )

    trip.refresh_from_db()
    assert trip.actual_arrival_at == earlier


def test_arriving_to_cancelled_leaves_arrival_null(session, tenant, controller, trip):
    """Un voyage annulé n'est pas arrivé — rien à horodater sur l'arrivée."""
    BatchEventProcessor(session=session, tenant=tenant, user=controller.user).process_batch(
        [_transition_event("cancelled")],
    )

    trip.refresh_from_db()
    assert trip.actual_arrival_at is None
    assert trip.status == Trip.Status.CANCELLED


# ─── Bloc 4 — `Trip.summary` à la fermeture ───

def _passenger(tenant, phone="+221770001010"):
    return Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop", phone=phone,
    )


def _booked(tenant, trip, status, seat_label, **extras):
    return Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=_passenger(tenant, phone=f"+221770{seat_label:>07}"),
        seat_label=seat_label, status=status, amount_xof=10000, **extras,
    )


def test_build_trip_summary_counts_each_category(tenant, trip, session, controller):
    _booked(tenant, trip, Reservation.Status.BOARDED, "A1")
    _booked(tenant, trip, Reservation.Status.BOARDED, "A2", sales_channel="onboard")
    _booked(tenant, trip, Reservation.Status.NO_SHOW, "B1")
    _booked(tenant, trip, Reservation.Status.REFUSED, "B2")
    CashEntry.objects.create(
        tenant=tenant, session=session, amount_xof=5000,
        reason=CashEntry.Reason.ONBOARD_SALE, collected_by=controller,
    )

    summary = build_trip_summary(trip)

    assert summary["boarded"] == 2
    assert summary["no_show"] == 1
    assert summary["refused"] == 1
    assert summary["onboard_sales"] == 1
    assert summary["revenue_xof"] == 20000  # 2 x 10000 pour les boarded
    assert summary["cash_xof"] == 5000
    assert "updated_at" in summary


def test_build_trip_summary_returns_zeros_not_nones(tenant, trip):
    """Un voyage vide doit rendre des zéros — lire un `None` forcerait un
    `coalesce` côté app."""
    summary = build_trip_summary(trip)

    assert summary["boarded"] == 0
    assert summary["revenue_xof"] == 0
    assert summary["cash_xof"] == 0
    assert summary["updated_at"]


def _close_url(trip):
    return f"/api/v1/voyage/trips/{trip.id}/control/close/"


def _close_body():
    return {"close_summary": {"notes": "RAS"}}


def _jwt_client(user):
    """
    `force_authenticate` ne traverse pas `TenantMiddleware` : `request.tenant`
    reste `None`, et `TripViewSet.get_queryset()` filtre par tenant — le trip
    devient alors introuvable. Un vrai JWT exerce le chemin complet.
    """
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_closing_a_session_writes_the_trip_summary(
    tenant, trip, session, controller,
):
    _booked(tenant, trip, Reservation.Status.BOARDED, "A1")

    client = _jwt_client(controller.user)
    response = client.post(_close_url(trip), _close_body(), format="json")

    assert response.status_code == 200, response.content
    trip.refresh_from_db()
    assert trip.summary["boarded"] == 1
    assert trip.summary["revenue_xof"] == 10000


def test_closing_a_second_session_recomputes_summary_not_accumulates(
    tenant, trip, controller,
):
    """
    Un trip peut avoir plusieurs sessions successives — relève à l'escale.
    `summary` reflète l'état courant, pas la somme des sessions.
    """
    _booked(tenant, trip, Reservation.Status.BOARDED, "A1")
    first = ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="D1", opened_at=timezone.now(),
    )
    client = _jwt_client(controller.user)
    client.post(_close_url(trip), _close_body(), format="json")

    trip.refresh_from_db()
    first_summary = trip.summary
    assert first_summary["boarded"] == 1

    # Nouvelle session, deuxième réservation posée en embarquement.
    _booked(tenant, trip, Reservation.Status.BOARDED, "A2")
    trip.status = Trip.Status.IN_TRANSIT
    trip.save(update_fields=["status"])
    ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="D2", opened_at=timezone.now(),
    )
    client.post(_close_url(trip), _close_body(), format="json")

    trip.refresh_from_db()
    assert trip.summary["boarded"] == 2  # pas 3
    assert trip.summary["updated_at"] >= first_summary["updated_at"]
    assert first.pk  # non silencé


def test_closing_a_session_without_any_reservation_writes_zeros(
    tenant, trip, session, controller,
):
    client = _jwt_client(controller.user)
    response = client.post(_close_url(trip), _close_body(), format="json")

    assert response.status_code == 200
    trip.refresh_from_db()
    assert trip.summary == {
        **trip.summary,  # updated_at variable
        "boarded": 0, "no_show": 0, "refused": 0,
        "onboard_sales": 0, "revenue_xof": 0, "cash_xof": 0,
    }


def test_closing_atomically_rolls_back_both_writes_on_trip_save_failure(
    tenant, trip, session, controller, monkeypatch,
):
    """
    Les deux `save()` tiennent ensemble : si le trip lève, la session reste
    ouverte. Sans la transaction, on aurait une session fermée avec un
    `summary` périmé, exactement le genre d'incohérence qu'on diagnostique
    plus tard en se grattant la tête.
    """
    assert session.closed_at is None

    def refuse(*args, **kwargs):
        raise DatabaseError("simulated")

    monkeypatch.setattr(Trip, "save", refuse)
    client = _jwt_client(controller.user)

    with pytest.raises(DatabaseError):
        client.post(_close_url(trip), _close_body(), format="json")

    session.refresh_from_db()
    assert session.closed_at is None  # rollback
