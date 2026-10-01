"""
TOUPAC Voyage — Chaque motif de rejet porte un code stable.

`rejection_reason` est du français, destiné à l'œil : il se reformule, se
traduit, s'enrichit. Une app qui bâtirait sa logique dessus casserait à la
première retouche de formulation. `rejection_code` est le pendant machine, et
ces tests vérifient qu'aucune branche de rejet n'y échappe — y compris celles
des handlers que personne ne regarde souvent.
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from colis.models import Order, Parcel
from geo.models import Place
from iam.models import Tenant, User
from voyage.models import (
    Anomaly,
    ControlEvent,
    Controller,
    ControlSession,
    Passenger,
    Reservation,
    Route,
    Trip,
)
from voyage.services.event_processor import VERDICT_DETAIL_KEYS, BatchEventProcessor
from voyage.services.exceptions import RejectionCode

pytestmark = pytest.mark.django_db


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Codes", slug="acme-codes")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@acme-codes.sn", password="TestPass#2026", first_name="Moussa",
        last_name="Sarr", tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-950")


@pytest.fixture
def trip(tenant):
    place = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    other = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.9246, 14.7886, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS",
        origin_place=place, destination_place=other,
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-CODES",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45, status=Trip.Status.SCHEDULED,
    )


@pytest.fixture
def session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="DEVICE-950", opened_at=timezone.now(),
    )


@pytest.fixture
def processor(session, tenant, controller):
    return BatchEventProcessor(session=session, tenant=tenant, user=controller.user)


def event(event_type, payload=None, **overrides):
    data = {
        "client_uuid": str(uuid.uuid4()),
        "event_type": event_type,
        "payload": payload if payload is not None else {},
        "created_at_local": timezone.now().isoformat(),
    }
    data.update(overrides)
    return data


def run(processor, event_data):
    return processor.process_batch([event_data])[0]


def code_of(processor, event_type, payload=None, **overrides):
    verdict = run(processor, event(event_type, payload, **overrides))
    assert verdict["status"] == "rejected", verdict
    return verdict["rejection_code"]


# ─── Couche batch : l'event n'atteint pas son handler ───

def test_a_non_object_event_is_malformed(processor):
    verdict = processor.process_batch(["pas un objet"])[0]

    assert verdict["rejection_code"] == RejectionCode.MALFORMED_EVENT


@pytest.mark.parametrize("bad", [None, "", "pas-un-uuid", 42])
def test_a_bad_client_uuid_is_named_as_such(processor, bad):
    verdict = run(processor, event("activity_transition", client_uuid=bad))

    assert verdict["rejection_code"] == RejectionCode.INVALID_CLIENT_UUID


def test_a_missing_event_type_is_named(processor):
    assert code_of(processor, None) == RejectionCode.MISSING_EVENT_TYPE


@pytest.mark.parametrize("bad", [None, "", "hier matin"])
def test_a_bad_created_at_is_named(processor, bad):
    verdict = run(processor, event("activity_transition", created_at_local=bad))

    assert verdict["rejection_code"] == RejectionCode.INVALID_CREATED_AT


def test_a_bad_gps_payload_is_named(processor):
    verdict = run(processor, event("activity_transition", gps_location={"lat": 14.7}))

    assert verdict["rejection_code"] == RejectionCode.INVALID_GPS


def test_a_bad_target_id_is_named(processor):
    verdict = run(processor, event("activity_transition", target_id="pas-un-uuid"))

    assert verdict["rejection_code"] == RejectionCode.INVALID_TARGET_ID


def test_an_unknown_event_type_is_named(processor):
    assert code_of(processor, "danse_de_la_pluie") == RejectionCode.UNKNOWN_EVENT_TYPE


def test_an_unexpected_handler_failure_falls_back_to_internal_error(processor, monkeypatch):
    """
    Le fourre-tout existe encore, et doit rester atteignable.

    Ce que le ticket cherche à réduire, c'est sa fréquence — pas son existence :
    une panne imprévue reste une panne imprévue.
    """
    from voyage.services import event_processor as module

    def boom(*args, **kwargs):
        raise RuntimeError("la base a disparu")

    monkeypatch.setitem(module.EVENT_HANDLERS, "activity_transition", boom)

    verdict = run(processor, event("activity_transition", {"to_status": "preparing"}))

    assert verdict["rejection_code"] == RejectionCode.INTERNAL_ERROR


def test_an_event_that_cannot_be_archived_is_named(processor, monkeypatch):
    """
    Distinct d'INTERNAL_ERROR : ici l'event n'a même pas de trace en base.

    L'app doit pouvoir le renvoyer, là où un INTERNAL_ERROR a déjà consommé son
    `client_uuid` et serait vu comme un doublon au rejeu.
    """
    from voyage.models import ControlEvent as CE

    original = CE.objects.create

    def refuse(*args, **kwargs):
        raise RuntimeError("archivage impossible")

    monkeypatch.setattr(CE.objects, "create", refuse)
    try:
        verdict = run(processor, event("activity_transition", {"to_status": "preparing"}))
    finally:
        monkeypatch.setattr(CE.objects, "create", original)

    assert verdict["rejection_code"] == RejectionCode.UNPROCESSABLE_EVENT


# ─── Embarquement ───

def test_boarding_without_a_reservation_id(processor):
    assert code_of(processor, "reservation_board") == RejectionCode.MISSING_RESERVATION_ID


def test_boarding_an_unknown_reservation(processor):
    code = code_of(processor, "reservation_board", {"reservation_id": str(uuid.uuid4())})

    assert code == RejectionCode.RESERVATION_NOT_FOUND


def test_boarding_a_reservation_that_is_not_boardable(processor, tenant, trip):
    """Un billet déjà embarqué : rejet propre, l'anomalie de doublon est gardée."""
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop", phone="+221770004444",
    )
    reservation = Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger, seat_label="A1",
        status=Reservation.Status.BOARDED, amount_xof=10000,
    )

    verdict = run(processor, event(
        "reservation_board", {"reservation_id": str(reservation.id)},
    ))

    assert verdict["rejection_code"] == RejectionCode.RESERVATION_NOT_BOARDABLE
    assert verdict["anomaly"]["type"] == Anomaly.Type.DUPLICATE_SCAN


# ─── Anomalies ───

def test_an_anomaly_without_a_title(processor):
    assert code_of(processor, "anomaly_create") == RejectionCode.MISSING_TITLE


def test_resolving_without_an_anomaly_id(processor):
    assert code_of(processor, "anomaly_resolve") == RejectionCode.MISSING_ANOMALY_ID


def test_resolving_an_unknown_anomaly(processor):
    code = code_of(processor, "anomaly_resolve", {"anomaly_id": str(uuid.uuid4())})

    assert code == RejectionCode.ANOMALY_NOT_FOUND


# ─── Incidents ───

def test_an_incident_without_a_title(processor):
    assert code_of(processor, "incident_create") == RejectionCode.MISSING_TITLE


def test_an_incident_on_an_unknown_trip(processor):
    code = code_of(
        processor, "incident_create", {"title": "Bagage suspect", "trip_id": str(uuid.uuid4())},
    )

    assert code == RejectionCode.TRIP_NOT_FOUND


# ─── Colis ───

def test_a_parcel_event_without_an_id(processor):
    assert code_of(processor, "parcel_verify") == RejectionCode.MISSING_PARCEL_ID
    assert code_of(processor, "parcel_refuse") == RejectionCode.MISSING_PARCEL_ID


def test_an_unknown_parcel(processor):
    code = code_of(processor, "parcel_verify", {"parcel_id": str(uuid.uuid4())})

    assert code == RejectionCode.PARCEL_NOT_FOUND


# ─── Transitions ───

def test_a_transition_without_a_target_status(processor):
    assert code_of(processor, "activity_transition") == RejectionCode.MISSING_TO_STATUS


def test_a_transition_to_a_status_that_does_not_exist(processor):
    code = code_of(processor, "activity_transition", {"to_status": "en_orbite"})

    assert code == RejectionCode.INVALID_TRIP_STATUS


def test_a_transition_on_an_unknown_trip(processor):
    code = code_of(processor, "activity_transition", {
        "to_status": "preparing", "trip_id": str(uuid.uuid4()),
    })

    assert code == RejectionCode.TRIP_NOT_FOUND


def test_a_transition_on_a_trip_outside_the_session(processor, tenant, trip):
    """Forger `payload.trip_id` pour faire transiter le voyage voisin."""
    neighbour = Trip.objects.create(
        tenant=tenant, route=trip.route, internal_id="VYG-VOISIN",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45,
    )

    code = code_of(processor, "activity_transition", {
        "to_status": "preparing", "trip_id": str(neighbour.id),
    })

    assert code == RejectionCode.TRIP_NOT_IN_SESSION


def test_a_transition_the_graph_forbids(processor, trip):
    """`scheduled` ne mène pas directement à `completed`."""
    code = code_of(processor, "activity_transition", {"to_status": "completed"})

    assert code == RejectionCode.TRANSITION_NOT_ALLOWED


# ─── Invariants transverses ───

def test_every_declared_code_is_reachable():
    """
    Chaque code de l'énumération est atteint par au moins un test de ce fichier
    ou du fichier de durcissement. Un code jamais produit est un code mort, et
    un code mort finit par mentir.
    """
    reached = set()
    scanned = (
        "test_batch_rejection_codes.py",
        "test_batch_hardening.py",
        "test_batch_stop_timestamps.py",
    )
    for path in scanned:
        source = (__file__.rsplit("test_batch_rejection_codes.py", 1)[0] + path)
        with open(source, encoding="utf-8") as handle:
            body = handle.read()
        reached |= {c for c in RejectionCode if f"RejectionCode.{c.name}" in body}

    assert reached == set(RejectionCode)


def test_an_accepted_verdict_carries_no_rejection_fields(processor):
    verdict = run(processor, event("activity_transition", {"to_status": "preparing"}))

    assert verdict["status"] == "accepted"
    assert "rejection_code" not in verdict
    assert "rejection_reason" not in verdict


def test_a_duplicate_verdict_carries_no_rejection_fields(processor):
    """Un rejeu de batch est normal, pas un échec : rien à expliquer."""
    data = event("activity_transition", {"to_status": "preparing"})
    run(processor, data)

    verdict = run(processor, data)

    assert verdict["status"] == "duplicate"
    assert "rejection_code" not in verdict
    assert "rejection_reason" not in verdict


def test_the_code_is_persisted_on_the_archived_event(processor):
    run(processor, event("anomaly_create"))

    archived = ControlEvent.objects.get()
    assert archived.status == ControlEvent.Status.REJECTED
    assert archived.rejection_code == RejectionCode.MISSING_TITLE
    assert archived.rejection_reason


def test_every_persisted_code_belongs_to_the_enumeration(processor, tenant, trip):
    """
    Le champ n'a pas de `choices` : c'est ce test qui tient la garantie.

    Un batch mêlant rejets et acceptations, pour que le contrôle porte aussi sur
    l'absence de code là où il n'y a pas de rejet.
    """
    processor.process_batch([
        event("anomaly_create"),
        event("parcel_verify"),
        event("activity_transition", {"to_status": "en_orbite"}),
        event("activity_transition", {"to_status": "preparing"}),
    ])

    persisted = set(
        ControlEvent.objects.exclude(rejection_code="")
        .values_list("rejection_code", flat=True),
    )
    assert persisted, "aucun code persisté — le test ne vérifierait rien"
    assert persisted <= {c.value for c in RejectionCode}
    assert not ControlEvent.objects.filter(
        status=ControlEvent.Status.PROCESSED,
    ).exclude(rejection_code="").exists()


def test_details_only_carry_the_declared_keys(processor, monkeypatch):
    """
    Une clé d'implémentation qui remonterait par accident deviendrait un contrat
    que personne n'a décidé — d'où la liste blanche plutôt qu'une fusion.
    """
    from voyage.services import event_processor as module

    def chatty(event_obj, tenant, session):
        return {
            "status": "accepted",
            "anomaly": None,
            "trip_id": str(session.trip_id),
            "trip_status": "preparing",
            "_cache_key": "secret-interne",
            "sql_debug": "SELECT 1",
        }

    monkeypatch.setitem(module.EVENT_HANDLERS, "activity_transition", chatty)

    verdict = run(processor, event("activity_transition", {"to_status": "preparing"}))

    assert set(verdict["details"]) == {"trip_id", "trip_status"}


def test_every_detail_key_table_targets_a_known_event_type():
    """Une entrée pour un type d'event qui n'existe plus ne servirait jamais."""
    from voyage.services.event_processor import EVENT_HANDLERS

    assert set(VERDICT_DETAIL_KEYS) <= set(EVENT_HANDLERS)


def test_a_handler_without_details_produces_no_details_key(processor):
    """`anomaly_create` rend son anomalie entière : `details` n'aurait rien à dire."""
    from voyage.models import Anomaly as A

    verdict = run(processor, event("anomaly_create", {"title": "Porte bloquée"}))

    assert verdict["status"] == "accepted"
    assert "details" not in verdict
    assert verdict["anomaly"]["id"] == str(A.objects.get().id)


def test_a_parcel_verdict_carries_its_identifier(processor, tenant):
    """Les colis aussi : l'app n'a pas à refetcher pour connaître le nouvel état."""
    order = Order.objects.create(
        tenant=tenant, internal_id="CMD-001",
        pickup_place=Place.objects.create(
            tenant=tenant, name="Retrait", type=Place.PlaceType.STATION,
            location=Point(-17.44, 14.69, srid=4326),
        ),
        dropoff_place=Place.objects.create(
            tenant=tenant, name="Livraison", type=Place.PlaceType.STATION,
            location=Point(-16.92, 14.78, srid=4326),
        ),
        status=Order.Status.CONFIRMED, total_amount_xof=5000,
        priority=Order.Priority.STANDARD, payment_status=Order.PaymentStatus.PENDING,
    )
    parcel = Parcel.objects.create(
        tenant=tenant, order=order, tracking_number="TRK-001",
        description="Carton", weight_kg=2, status=Parcel.Status.CREATED,
    )

    verdict = run(processor, event("parcel_verify", {"parcel_id": str(parcel.id)}))

    assert verdict["details"] == {
        "parcel_id": str(parcel.id), "parcel_status": Parcel.Status.IN_TRANSIT,
    }
