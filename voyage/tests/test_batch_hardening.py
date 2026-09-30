"""
TOUPAC Voyage — Contrat durci des events de contrôle.

Deux sujets se croisent ici, et ils ont la même cause : un contrôleur travaille
hors réseau, et sa saisie n'est arbitrée par rien avant d'atteindre le serveur.

- **La vente à bord** acceptait n'importe quel siège, forçait le moyen de
  paiement, et se contentait d'un passager sans nom. Un conflit de siège tombait
  en `IntegrityError` sur la contrainte de base, donc en « erreur interne » du
  point de vue de l'app.
- **Le verdict** ne portait qu'un motif en français libre. L'app pouvait
  l'afficher, jamais en déduire quoi faire.
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from geo.models import Place
from iam.models import Tenant, User
from voyage.models import (
    Anomaly,
    CashEntry,
    Controller,
    ControlSession,
    Passenger,
    Reservation,
    Route,
    SeatMap,
    Trip,
)
from voyage.services.event_processor import BatchEventProcessor
from voyage.services.exceptions import RejectionCode

pytestmark = pytest.mark.django_db


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Acme", slug="acme-batch")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@acme-batch.sn", password="TestPass#2026", first_name="Moussa",
        last_name="Sarr", tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-900")


@pytest.fixture
def trip(tenant):
    """Un voyage doté d'un plan de sièges 2x3 — A1, B1, C1, A2, B2, C2."""
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Bamako", type=Place.PlaceType.STATION,
        location=Point(-8.0029, 12.6392, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code="DKR-BKO",
        origin_place=origin, destination_place=destination,
    )
    seat_map = SeatMap.objects.create(
        tenant=tenant, name="Car 6 places", total_seats=6,
        layout={"rows": 2, "cols": 3},
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-001",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6, seat_map=seat_map, status=Trip.Status.BOARDING,
    )


@pytest.fixture
def session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="DEVICE-900", opened_at=timezone.now(),
    )


@pytest.fixture
def processor(session, tenant, controller):
    return BatchEventProcessor(session=session, tenant=tenant, user=controller.user)


PASSENGER = {"first_name": "Awa", "last_name": "Diop", "phone": "+221770001234"}


def sale_event(**payload_overrides):
    payload = {"seat_label": "A1", "amount_xof": 12000, "passenger_data": dict(PASSENGER)}
    payload.update(payload_overrides)
    return {
        "client_uuid": str(uuid.uuid4()),
        "event_type": "onboard_sale",
        "payload": payload,
        "created_at_local": timezone.now().isoformat(),
    }


def sell(processor, **overrides):
    """Traite une vente à bord et rend son verdict."""
    return processor.process_batch([sale_event(**overrides)])[0]


def existing_reservation(tenant, trip, seat_label, status):
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Fatou", last_name="Mbaye", phone="+221770009999",
    )
    return Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger, seat_label=seat_label,
        status=status, amount_xof=10000,
    )


# ─── La vente nominale ───

def test_a_sale_creates_the_passenger_the_reservation_and_the_cash_entry(
    processor, tenant, trip,
):
    verdict = sell(processor)

    assert verdict["status"] == "accepted"
    assert verdict["anomaly"] is None
    assert "rejection_code" not in verdict

    reservation = Reservation.objects.get()
    assert reservation.seat_label == "A1"
    assert reservation.status == Reservation.Status.BOARDED
    assert reservation.sales_channel == "onboard"
    assert reservation.boarding_method == "manual"
    assert CashEntry.objects.get().reservation_id == reservation.id
    assert Passenger.objects.get().first_name == "Awa"


def test_the_verdict_carries_what_the_app_would_otherwise_refetch(processor, trip):
    """C'est l'intérêt de `details` : pas de manifeste à recharger après coup."""
    details = sell(processor)["details"]

    assert set(details) == {
        "reservation_id", "passenger_id", "cash_entry_id",
        "reservation_status", "trip_status",
    }
    assert details["reservation_id"] == str(Reservation.objects.get().id)
    assert details["passenger_id"] == str(Passenger.objects.get().id)
    assert details["cash_entry_id"] == str(CashEntry.objects.get().id)
    assert details["reservation_status"] == Reservation.Status.BOARDED
    assert details["trip_status"] == Trip.Status.BOARDING


def test_a_known_phone_reuses_the_existing_passenger_record(processor, tenant):
    known = Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop", phone="+221770001234",
    )

    sell(processor)

    assert Passenger.objects.count() == 1
    assert Reservation.objects.get().passenger_id == known.id


def test_the_seat_count_of_the_trip_is_incremented(processor, trip):
    sell(processor)

    trip.refresh_from_db()
    assert trip.booked_seats == 1


# ─── Le passager ───

@pytest.mark.parametrize("passenger_data", [
    None, {}, {"last_name": "Diop"}, {"first_name": "Awa"},
    {"first_name": "", "last_name": "Diop"}, {"first_name": "Awa", "last_name": "   "},
])
def test_a_sale_without_a_named_passenger_is_refused(processor, passenger_data):
    """
    Sans nom, le billet désigne un fantôme.

    Le champ était de fait optionnel : `passenger_data.get("first_name", "")`
    laissait passer une fiche vide, impossible à rapprocher de qui que ce soit.
    """
    verdict = sell(processor, passenger_data=passenger_data)

    assert verdict["status"] == "rejected"
    assert verdict["rejection_code"] == RejectionCode.MISSING_PASSENGER_DATA
    assert not Passenger.objects.exists()
    assert not Reservation.objects.exists()


def test_the_phone_stays_optional(processor):
    """Il ne sert qu'à retrouver une fiche existante, pas à identifier."""
    verdict = sell(processor, passenger_data={"first_name": "Awa", "last_name": "Diop"})

    assert verdict["status"] == "accepted"
    assert Passenger.objects.get().phone == ""


# ─── Le siège ───

def test_a_sale_without_a_seat_is_refused(processor):
    verdict = sell(processor, seat_label=None)

    assert verdict["rejection_code"] == RejectionCode.MISSING_SEAT_LABEL


def test_a_sale_without_an_amount_is_refused(processor):
    verdict = sell(processor, amount_xof=None)

    assert verdict["rejection_code"] == RejectionCode.MISSING_AMOUNT


def test_a_seat_outside_the_plan_is_refused(processor):
    """Le plan déclare A1..C2 : Z9 n'existe sur aucun véhicule."""
    verdict = sell(processor, seat_label="Z9")

    assert verdict["status"] == "rejected"
    assert verdict["rejection_code"] == RejectionCode.INVALID_SEAT_LABEL
    assert not Reservation.objects.exists()


def test_every_seat_of_the_plan_is_accepted(processor, trip):
    """Le contrôle ne doit pas refuser des sièges qui existent bel et bien."""
    for seat in ("A1", "B1", "C1", "A2", "B2", "C2"):
        assert sell(processor, seat_label=seat)["status"] == "accepted"


def test_a_trip_without_a_seat_plan_accepts_any_label(processor, trip):
    """
    Pas de plan déclaré ne veut pas dire plan vide.

    Refuser tous les sièges sur un voyage sans `seat_map` — configuration
    parfaitement légitime — rendrait la vente à bord impossible.
    """
    trip.seat_map = None
    trip.save(update_fields=["seat_map"])

    assert sell(processor, seat_label="QUELCONQUE")["status"] == "accepted"


def test_an_explicit_seat_layout_is_honoured(processor, trip):
    """Second format de `layout` : la liste explicite prime sur la grille."""
    trip.seat_map.layout = {"seats": [{"label": "1A"}, {"label": "1B"}]}
    trip.seat_map.save(update_fields=["layout"])

    assert sell(processor, seat_label="1A")["status"] == "accepted"
    assert sell(processor, seat_label="A1")["rejection_code"] == (
        RejectionCode.INVALID_SEAT_LABEL
    )


# ─── Le conflit de siège ───

@pytest.mark.parametrize("occupying_status", [
    Reservation.Status.BOOKED,
    Reservation.Status.CHECKED_IN,
    Reservation.Status.BOARDED,
    # `no_show` retient le siège : il est attribué à qui ne s'est pas présenté,
    # et la contrainte de base le compte comme actif.
    Reservation.Status.NO_SHOW,
])
def test_an_occupied_seat_is_refused_with_an_anomaly(
    processor, tenant, trip, occupying_status,
):
    """
    Le cas qui tombait en `IntegrityError`, donc en « erreur interne ».

    L'anomalie doit survivre au rejet : c'est elle qui documente le conflit pour
    l'exploitation, et un rollback du savepoint l'effacerait.
    """
    existing_reservation(tenant, trip, "A1", occupying_status)

    verdict = sell(processor)

    assert verdict["status"] == "rejected"
    assert verdict["rejection_code"] == RejectionCode.SEAT_ALREADY_TAKEN
    assert "A1" in verdict["rejection_reason"]
    assert verdict["anomaly"]["type"] == Anomaly.Type.SEAT_CONFLICT
    assert verdict["anomaly"]["severity"] == Anomaly.Severity.MODERATE
    assert Anomaly.objects.count() == 1
    assert Reservation.objects.count() == 1  # aucune nouvelle réservation


@pytest.mark.parametrize("freeing_status", [
    Reservation.Status.CANCELLED, Reservation.Status.REFUSED,
])
def test_a_cancelled_or_refused_seat_is_free_again(
    processor, tenant, trip, freeing_status,
):
    """Mêmes statuts que la contrainte `unique_active_seat_per_trip`."""
    existing_reservation(tenant, trip, "A1", freeing_status)

    assert sell(processor)["status"] == "accepted"


def test_the_pre_check_covers_exactly_what_the_database_constraint_covers(
    processor, tenant, trip,
):
    """
    Invariant : aucun statut ne doit passer la vérification pour tomber en base.

    Si les deux ensembles divergeaient, le cas passé entre les mailles
    ressortirait en `IntegrityError` — le défaut même que ce handler supprime.
    """
    from voyage.services.handlers.sales import VOID_RESERVATION_STATUSES

    constraint = next(
        c for c in Reservation._meta.constraints
        if c.name == "unique_active_seat_per_trip"
    )
    # La condition est `~Q(status__in=[...])` : on en extrait la liste.
    negated = constraint.condition.children[0][1]

    assert set(VOID_RESERVATION_STATUSES) == set(negated)


# ─── Le moyen de paiement ───

def test_the_payment_method_defaults_to_onboard_cash(processor):
    """Comportement historique préservé : les appelants n'envoient pas le champ."""
    assert sell(processor)["status"] == "accepted"
    assert Reservation.objects.get().payment_method == "onboard_cash"


@pytest.mark.parametrize("method", [
    "cash", "wave", "orange_money", "free_money", "mtn_momo", "onboard_cash",
])
def test_each_allowed_payment_method_is_accepted(processor, method):
    seat = {"cash": "A1", "wave": "B1", "orange_money": "C1",
            "free_money": "A2", "mtn_momo": "B2", "onboard_cash": "C2"}[method]

    verdict = sell(processor, payment_method=method, seat_label=seat)

    assert verdict["status"] == "accepted"
    assert Reservation.objects.get(seat_label=seat).payment_method == method


def test_an_unknown_payment_method_is_refused(processor):
    """
    Le champ n'avait aucune validation — et le handler écrasait de toute façon
    ce que l'app envoyait par « onboard_cash ».
    """
    verdict = sell(processor, payment_method="bitcoin")

    assert verdict["rejection_code"] == RejectionCode.INVALID_PAYMENT_METHOD
    assert not Reservation.objects.exists()


# ─── Le voyage visé ───

def test_an_absent_trip_id_falls_back_to_the_session_trip(processor, trip):
    assert sell(processor)["status"] == "accepted"
    assert Reservation.objects.get().trip_id == trip.id


def test_an_unknown_trip_id_is_refused(processor):
    verdict = sell(processor, trip_id=str(uuid.uuid4()))

    assert verdict["rejection_code"] == RejectionCode.TRIP_NOT_FOUND


def test_a_trip_of_another_tenant_is_refused(processor, trip):
    """Le filtre porte sur le tenant : un identifiant voisin ne doit rien ouvrir."""
    other = Tenant.objects.create(name="Concurrent", slug="concurrent-batch")
    foreign = Trip.objects.create(
        tenant=other, route=trip.route, internal_id="VYG-X",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6,
    )

    verdict = sell(processor, trip_id=str(foreign.id))

    assert verdict["rejection_code"] == RejectionCode.TRIP_NOT_FOUND
