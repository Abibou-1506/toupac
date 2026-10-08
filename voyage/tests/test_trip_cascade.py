"""
TOUPAC Voyage — Cascade terminale Trip → Reservations.

Quand un `Trip` transite vers `COMPLETED` ou `CANCELLED`, les
réservations encore `BOOKED` basculent en `NO_SHOW` et celles en
`CHECKED_IN` basculent en `BOARDED`. La règle vit dans
`voyage/signals.py:cascade_reservations_on_trip_terminal` — hookée en
`post_save(Trip)` pour couvrir toutes les sources de mutation (vue,
batch mobile, admin, celery, shell).

Les tests ci-dessous couvrent :
- Le mapping BOOKED → NO_SHOW et les statuts non impactés
- Le mapping CHECKED_IN → BOARDED
- La cascade sur CANCELLED (même règle que COMPLETED)
- L'idempotence : save sans changement de statut n'altère rien
- L'idempotence : COMPLETED → COMPLETED ne redéclenche pas
- L'intégration end-to-end via l'endpoint `/trips/{id}/control/close/`
"""
import datetime

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
    Passenger,
    Reservation,
    Route,
    Trip,
)

pytestmark = pytest.mark.django_db


# ─── Décor minimal ───


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Cascade", slug="cascade")


@pytest.fixture
def route(tenant):
    place = Place.objects.create(
        tenant=tenant,
        name="Dakar",
        type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    other = Place.objects.create(
        tenant=tenant,
        name="Thiès",
        type=Place.PlaceType.STATION,
        location=Point(-16.9246, 14.7886, srid=4326),
    )
    return Route.objects.create(
        tenant=tenant,
        name="Dakar → Thiès",
        code="DKR-THS",
        origin_place=place,
        destination_place=other,
    )


@pytest.fixture
def trip(tenant, route):
    return Trip.objects.create(
        tenant=tenant,
        route=route,
        internal_id="VYG-C01",
        departure_date=timezone.now().date(),
        scheduled_at=timezone.now(),
        total_seats=45,
        status=Trip.Status.ARRIVING,
    )


def _make_passenger(tenant, phone):
    return Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop", phone=phone,
    )


def _make_reservation(tenant, trip, status, seat_label, phone):
    return Reservation.objects.create(
        tenant=tenant,
        trip=trip,
        passenger=_make_passenger(tenant, phone),
        seat_label=seat_label,
        status=status,
        amount_xof=3500,
    )


# ─── Mapping BOOKED → NO_SHOW ───


def test_trip_to_completed_cascades_booked_to_no_show(tenant, trip):
    r_booked = _make_reservation(tenant, trip, Reservation.Status.BOOKED, "A1", "+221770000001")
    r_boarded = _make_reservation(tenant, trip, Reservation.Status.BOARDED, "A2", "+221770000002")
    r_cancelled = _make_reservation(tenant, trip, Reservation.Status.CANCELLED, "A3", "+221770000003")

    trip.status = Trip.Status.COMPLETED
    trip.save(update_fields=["status", "updated_at"])

    r_booked.refresh_from_db()
    r_boarded.refresh_from_db()
    r_cancelled.refresh_from_db()
    assert r_booked.status == Reservation.Status.NO_SHOW
    assert r_boarded.status == Reservation.Status.BOARDED
    assert r_cancelled.status == Reservation.Status.CANCELLED


# ─── Mapping CHECKED_IN → BOARDED ───


def test_trip_to_completed_cascades_checked_in_to_boarded(tenant, trip):
    r = _make_reservation(tenant, trip, Reservation.Status.CHECKED_IN, "B1", "+221770000011")
    assert r.boarded_at is None

    trip.status = Trip.Status.COMPLETED
    trip.save(update_fields=["status", "updated_at"])

    r.refresh_from_db()
    assert r.status == Reservation.Status.BOARDED
    # `boarded_at` existe sur Reservation : la cascade le pose à la clôture.
    assert r.boarded_at is not None


# ─── CANCELLED déclenche aussi la cascade ───


def test_trip_to_cancelled_cascades_same_way(tenant, trip):
    r_booked = _make_reservation(tenant, trip, Reservation.Status.BOOKED, "C1", "+221770000021")
    r_checked_in = _make_reservation(tenant, trip, Reservation.Status.CHECKED_IN, "C2", "+221770000022")
    r_refused = _make_reservation(tenant, trip, Reservation.Status.REFUSED, "C3", "+221770000023")

    trip.status = Trip.Status.CANCELLED
    trip.save(update_fields=["status", "updated_at"])

    r_booked.refresh_from_db()
    r_checked_in.refresh_from_db()
    r_refused.refresh_from_db()
    assert r_booked.status == Reservation.Status.NO_SHOW
    assert r_checked_in.status == Reservation.Status.BOARDED
    assert r_refused.status == Reservation.Status.REFUSED


# ─── Idempotence : save sans transition ne touche rien ───


def test_trip_save_without_status_change_does_not_touch_reservations(tenant, trip):
    r_booked = _make_reservation(tenant, trip, Reservation.Status.BOOKED, "D1", "+221770000031")
    r_checked_in = _make_reservation(tenant, trip, Reservation.Status.CHECKED_IN, "D2", "+221770000032")

    # Modif anodine (pas de status) sur un trip encore non terminal.
    trip.summary = {"foo": "bar"}
    trip.save(update_fields=["summary", "updated_at"])

    r_booked.refresh_from_db()
    r_checked_in.refresh_from_db()
    assert r_booked.status == Reservation.Status.BOOKED
    assert r_checked_in.status == Reservation.Status.CHECKED_IN


# ─── Idempotence : COMPLETED → COMPLETED ne redéclenche pas ───


def test_trip_already_completed_resaved_does_not_duplicate_cascade(tenant, trip):
    r = _make_reservation(tenant, trip, Reservation.Status.BOARDED, "E1", "+221770000041")
    # Simule un embarquement effectif avant clôture : le contrôleur a posé
    # son propre `boarded_at` au moment du scan.
    scanned_at = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)
    r.boarded_at = scanned_at
    r.save(update_fields=["boarded_at", "updated_at"])

    trip.status = Trip.Status.COMPLETED
    trip.save(update_fields=["status", "updated_at"])
    r.refresh_from_db()
    first_boarded_at = r.boarded_at

    # Resave COMPLETED → COMPLETED : la cascade ne doit pas réécrire
    # `boarded_at` (sinon on perd l'horodatage du scan réel).
    trip.summary = {"other": "payload"}
    trip.save(update_fields=["status", "summary", "updated_at"])
    r.refresh_from_db()
    assert r.status == Reservation.Status.BOARDED
    assert r.boarded_at == first_boarded_at


# ─── Intégration end-to-end via l'endpoint control/close ───


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@cascade.sn",
        password="TestPass#2026",
        first_name="Moussa",
        last_name="Sarr",
        tenant=tenant,
        role=User.Role.CONTROLLER,
        is_staff=True,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-C01")


@pytest.fixture
def open_session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant,
        trip=trip,
        controller=controller,
        device_id="DEVICE-C01",
        opened_at=timezone.now(),
    )


def test_control_close_endpoint_triggers_cascade(tenant, controller, trip, open_session):
    r_booked = _make_reservation(tenant, trip, Reservation.Status.BOOKED, "F1", "+221770000051")
    r_checked_in = _make_reservation(tenant, trip, Reservation.Status.CHECKED_IN, "F2", "+221770000052")

    # `force_authenticate` ne traverse pas `TenantMiddleware` : `request.tenant`
    # resterait None et `TripViewSet.get_queryset()` filtrerait le trip hors
    # scope. On passe par un vrai JWT comme le fait `test_trip_lifecycle`.
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(controller.user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    payload = {"close_summary": {"notes": "RAS cascade"}}
    response = client.post(
        f"/api/v1/voyage/trips/{trip.id}/control/close/", payload, format="json",
    )
    assert response.status_code == 200, response.content

    trip.refresh_from_db()
    assert trip.status == Trip.Status.COMPLETED

    r_booked.refresh_from_db()
    r_checked_in.refresh_from_db()
    assert r_booked.status == Reservation.Status.NO_SHOW
    assert r_checked_in.status == Reservation.Status.BOARDED
