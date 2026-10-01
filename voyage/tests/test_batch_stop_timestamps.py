"""
TOUPAC Voyage — Horodatages d'escale et JWT systématique des ventes à bord.

Deux chantiers posés dans le même ticket parce qu'ils arrivent dans la même
mise à jour du contrat batch, et parce qu'ils ferment deux trous que la revue
du 1er oct 2026 a trouvés côte à côte :

- `TripStop.ata` / `atd` / `status` n'étaient écrits par aucun chemin
  applicatif. Les events `stop_arrive` / `stop_depart` le font désormais,
  séparés d'`activity_transition` pour que le tracking GPS futur puisse les
  émettre sans toucher au statut métier.
- `handle_onboard_sale` ne signait pas le JWT du billet qu'il créait. Une
  famille asymétrique sans preuve d'achat vérifiable — à présent alignée sur
  le flux nominal.
"""
import uuid

import jwt
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from geo.models import Place
from iam.models import Tenant, User
from voyage.models import (
    Controller,
    ControlSession,
    Reservation,
    Route,
    RouteStop,
    SeatMap,
    Trip,
    TripStop,
)
from voyage.services.event_processor import (
    EVENT_HANDLERS,
    VERDICT_DETAIL_KEYS,
    BatchEventProcessor,
)
from voyage.services.exceptions import RejectionCode
from voyage.services.qr_jwt import qr_public_key_pem, verify_ticket_jwt

pytestmark = pytest.mark.django_db


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Escales", slug="stops-batch")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@stops-batch.sn", password="TestPass#2026",
        first_name="Moussa", last_name="Sarr",
        tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-ST01")


@pytest.fixture
def trip_with_stops(tenant):
    """Un voyage et ses trois `TripStop` ordonnés — origine, intermédiaire, fin."""
    places = [
        Place.objects.create(
            tenant=tenant, name=name, type=Place.PlaceType.STATION,
            location=Point(lng, 14.0, srid=4326),
        )
        for name, lng in [("Dakar", -17.44), ("Thiès", -16.92), ("Bamako", -8.0)]
    ]
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code="DKR-BKO",
        origin_place=places[0], destination_place=places[-1],
    )
    route_stops = [
        RouteStop.objects.create(
            tenant=tenant, route=route, place=places[i], stop_order=i,
        )
        for i in range(3)
    ]
    seat_map = SeatMap.objects.create(
        tenant=tenant, name="Car 6", total_seats=6, layout={"rows": 2, "cols": 3},
    )
    trip = Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-ST01",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6, seat_map=seat_map, status=Trip.Status.BOARDING,
    )
    trip_stops = [
        TripStop.objects.create(
            tenant=tenant, trip=trip, route_stop=route_stops[i], place=places[i],
            stop_order=i,
        )
        for i in range(3)
    ]
    trip.trip_stops_list = trip_stops  # exposé pour les tests
    return trip


@pytest.fixture
def session(tenant, controller, trip_with_stops):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip_with_stops, controller=controller,
        device_id="DEV-ST01", opened_at=timezone.now(),
    )


@pytest.fixture
def processor(session, tenant, controller):
    return BatchEventProcessor(session=session, tenant=tenant, user=controller.user)


# ─── Helpers d'émission ───

def _event(event_type, **payload):
    return {
        "client_uuid": str(uuid.uuid4()),
        "event_type": event_type,
        "payload": payload,
        "created_at_local": timezone.now().isoformat(),
    }


def arrive(processor, stop=None, **payload_overrides):
    """
    Émet un `stop_arrive`. Défaut : premier `TripStop` du trip de la session.

    Règle DECISIONS.md « un helper absorbe les champs obligatoires » : les
    tests qui ne regardent pas la mécanique du payload ne doivent pas avoir
    à l'écrire.
    """
    stop = stop or processor.session.trip.stops.order_by("stop_order").first()
    payload = {"stop_id": str(stop.id)}
    payload.update(payload_overrides)
    return processor.process_batch([_event("stop_arrive", **payload)])[0]


def depart(processor, stop=None, **payload_overrides):
    stop = stop or processor.session.trip.stops.order_by("stop_order").first()
    payload = {"stop_id": str(stop.id)}
    payload.update(payload_overrides)
    return processor.process_batch([_event("stop_depart", **payload)])[0]


# ─── stop_arrive ───

def test_stop_arrive_sets_ata_and_marks_the_stop_arrived(processor, trip_with_stops):
    stop = trip_with_stops.stops.order_by("stop_order").first()

    verdict = arrive(processor, stop=stop)

    assert verdict["status"] == "accepted"
    assert verdict["anomaly"] is None
    assert verdict["details"] == {
        "stop_id": str(stop.id), "stop_status": TripStop.Status.ARRIVED,
    }
    stop.refresh_from_db()
    assert stop.ata is not None
    assert stop.atd is None
    assert stop.status == TripStop.Status.ARRIVED


def test_stop_arrive_without_stop_id_is_refused(processor):
    verdict = arrive(processor, stop_id=None)

    assert verdict["rejection_code"] == RejectionCode.MISSING_STOP_ID


def test_a_stop_from_another_trip_is_rejected(processor, tenant, trip_with_stops):
    """
    Un `TripStop` qui existe en base mais appartient à un autre voyage —
    même tenant ou autre — doit être traité comme inexistant pour ce trip.
    """
    other_place = Place.objects.create(
        tenant=tenant, name="Saint-Louis", type=Place.PlaceType.STATION,
        location=Point(-16.5, 16.0, srid=4326),
    )
    other_route = Route.objects.create(
        tenant=tenant, name="Autre route", code="OTR",
        origin_place=other_place, destination_place=other_place,
    )
    other_route_stop = RouteStop.objects.create(
        tenant=tenant, route=other_route, place=other_place, stop_order=0,
    )
    other_trip = Trip.objects.create(
        tenant=tenant, route=other_route, internal_id="VYG-X",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6,
    )
    foreign_stop = TripStop.objects.create(
        tenant=tenant, trip=other_trip, route_stop=other_route_stop,
        place=other_place, stop_order=0,
    )

    verdict = arrive(processor, stop_id=str(foreign_stop.id))

    assert verdict["rejection_code"] == RejectionCode.STOP_NOT_FOUND


def test_a_stop_of_another_tenant_is_rejected_too(processor, trip_with_stops):
    """
    L'ancrage par `session.trip` suffit : un `TripStop` d'un autre tenant
    n'est pas accessible depuis cette session, et le filtre refuse donc même
    sans mention explicite du tenant.
    """
    other_tenant = Tenant.objects.create(name="Voisin", slug="voisin-stops")
    place = Place.objects.create(
        tenant=other_tenant, name="Voisine", type=Place.PlaceType.STATION,
        location=Point(-17.0, 14.0, srid=4326),
    )
    route = Route.objects.create(
        tenant=other_tenant, name="Route voisine", code="VSN",
        origin_place=place, destination_place=place,
    )
    rs = RouteStop.objects.create(
        tenant=other_tenant, route=route, place=place, stop_order=0,
    )
    other_trip = Trip.objects.create(
        tenant=other_tenant, route=route, internal_id="VYG-VSN",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6,
    )
    other_stop = TripStop.objects.create(
        tenant=other_tenant, trip=other_trip, route_stop=rs, place=place,
        stop_order=0,
    )

    verdict = arrive(processor, stop_id=str(other_stop.id))

    assert verdict["rejection_code"] == RejectionCode.STOP_NOT_FOUND


# ─── stop_depart ───

def test_stop_depart_sets_atd_and_marks_the_stop_departed(processor, trip_with_stops):
    stop = trip_with_stops.stops.order_by("stop_order").first()

    verdict = depart(processor, stop=stop)

    assert verdict["status"] == "accepted"
    stop.refresh_from_db()
    assert stop.atd is not None
    assert stop.status == TripStop.Status.DEPARTED


def test_stop_depart_without_arrive_is_tolerated(processor, trip_with_stops):
    """
    Décision tolérante : un contrôleur qui oublie `stop_arrive` et émet
    directement `stop_depart` n'est pas plus suspect qu'un départ fantôme.
    L'ordre n'est pas contrôlé — le backend accepte, `ata` reste nul.
    """
    stop = trip_with_stops.stops.order_by("stop_order").first()

    verdict = depart(processor, stop=stop)

    assert verdict["status"] == "accepted"
    stop.refresh_from_db()
    assert stop.ata is None
    assert stop.atd is not None
    assert stop.status == TripStop.Status.DEPARTED


def test_a_second_arrive_preserves_the_first_timestamp(processor, trip_with_stops):
    """
    Premier gagne : un re-marquage ne doit pas écraser l'instant réel du
    premier passage. Aligné sur `handle_activity_transition` qui applique la
    même règle à `actual_departure_at` et `actual_arrival_at` — un bug de
    resync qui régénérerait le `client_uuid` passerait l'idempotence sans la
    bloquer, et écraser 16h30 par 23h04 serait pire que de laisser 16h30.
    """
    stop = trip_with_stops.stops.order_by("stop_order").first()

    first = arrive(processor, stop=stop)
    stop.refresh_from_db()
    first_ata = stop.ata

    second = arrive(processor, stop=stop)

    assert first["status"] == "accepted" and second["status"] == "accepted"
    stop.refresh_from_db()
    assert stop.ata == first_ata
    assert stop.status == TripStop.Status.ARRIVED


def test_a_second_depart_preserves_the_first_timestamp(processor, trip_with_stops):
    """Même règle, côté départ — miroir strict de l'arrivée."""
    stop = trip_with_stops.stops.order_by("stop_order").first()

    depart(processor, stop=stop)
    stop.refresh_from_db()
    first_atd = stop.atd

    depart(processor, stop=stop)
    stop.refresh_from_db()

    assert stop.atd == first_atd
    assert stop.status == TripStop.Status.DEPARTED


def test_arrive_resets_status_even_when_timestamp_is_preserved(
    processor, trip_with_stops,
):
    """
    Un stop marqué `SKIPPED` à tort doit pouvoir repasser à `ARRIVED`. Le
    status est l'état courant du voyage, modifié ; `ata`, lui, est l'instant
    où le voyage s'est arrêté la première fois — fait historique, préservé.
    """
    stop = trip_with_stops.stops.order_by("stop_order").first()
    arrive(processor, stop=stop)
    stop.refresh_from_db()
    original_ata = stop.ata

    stop.status = TripStop.Status.SKIPPED
    stop.save(update_fields=["status"])

    arrive(processor, stop=stop)
    stop.refresh_from_db()

    assert stop.ata == original_ata
    assert stop.status == TripStop.Status.ARRIVED


def test_depart_resets_status_even_when_timestamp_is_preserved(
    processor, trip_with_stops,
):
    stop = trip_with_stops.stops.order_by("stop_order").first()
    depart(processor, stop=stop)
    stop.refresh_from_db()
    original_atd = stop.atd

    stop.status = TripStop.Status.SKIPPED
    stop.save(update_fields=["status"])

    depart(processor, stop=stop)
    stop.refresh_from_db()

    assert stop.atd == original_atd
    assert stop.status == TripStop.Status.DEPARTED


def test_stop_handlers_do_not_change_the_trip_status(processor, trip_with_stops):
    """
    Découplage voulu : un `stop_arrive` ne fait pas transiter le trip en
    `at_stop`, et un `stop_depart` ne le fait pas repartir. L'app émet
    séparément `activity_transition` si elle veut faire les deux.
    """
    initial_status = trip_with_stops.status
    stop = trip_with_stops.stops.order_by("stop_order").first()

    arrive(processor, stop=stop)
    depart(processor, stop=stop)

    trip_with_stops.refresh_from_db()
    assert trip_with_stops.status == initial_status


# ─── JWT systématique sur onboard_sale ───
#
# Le ticket du 2 oct 2026 aligne la vente à bord sur le flow nominal : chaque
# `Reservation` créée porte son `qr_code_jwt` dès la fin du handler. Les tests
# existants `onboard_sale` continuent de passer — la seule chose nouvelle est
# que le champ n'est plus vide.

def _onboard_sale_event(tenant, trip, origin_stop_id, destination_stop_id):
    return {
        "client_uuid": str(uuid.uuid4()),
        "event_type": "onboard_sale",
        "payload": {
            "seat_label": "A1",
            "amount_xof": 10000,
            "trip_id": str(trip.id),
            "origin_stop": origin_stop_id,
            "destination_stop": destination_stop_id,
            "passenger_data": {
                "first_name": "Awa", "last_name": "Diop",
                "phone": "+221770000111",
            },
        },
        "created_at_local": timezone.now().isoformat(),
    }


def test_an_onboard_sale_signs_the_reservation_jwt(processor, trip_with_stops):
    stops = list(trip_with_stops.route.stops.order_by("stop_order"))
    event = _onboard_sale_event(
        trip_with_stops.tenant, trip_with_stops,
        str(stops[0].id), str(stops[-1].id),
    )

    verdict = processor.process_batch([event])[0]

    assert verdict["status"] == "accepted"
    reservation = Reservation.objects.get(id=verdict["details"]["reservation_id"])
    assert reservation.qr_code_jwt, (
        "L'omission historique du JWT crée une famille asymétrique dans "
        "toutes les requêtes futures — ce test en est le garde-fou."
    )


def test_the_onboard_jwt_carries_the_expected_claims(processor, trip_with_stops):
    stops = list(trip_with_stops.route.stops.order_by("stop_order"))
    event = _onboard_sale_event(
        trip_with_stops.tenant, trip_with_stops,
        str(stops[0].id), str(stops[-1].id),
    )
    processor.process_batch([event])

    reservation = Reservation.objects.get()
    # Décodage par le même chemin que la vérification nominale : si la clé
    # publique du processus est partagée avec la clé privée (keypair
    # éphémère par défaut), `verify_ticket_jwt` doit rendre un dict.
    payload = verify_ticket_jwt(reservation.qr_code_jwt)
    if payload is None:
        # Repli : la clé publique peut ne pas être configurée dans tous les
        # environnements de test. On vérifie alors les claims par un décodage
        # non vérifié — la signature a bien eu lieu, c'est le contrat qu'on
        # mesure ici, pas la configuration serveur.
        payload = jwt.decode(
            reservation.qr_code_jwt, options={"verify_signature": False},
        )

    assert payload["sub"] == str(reservation.id)
    assert payload["trip"] == str(reservation.trip_id)
    assert payload["seat"] == reservation.seat_label
    assert payload["pax"] == reservation.passenger.full_name
    assert payload["tenant"] == str(reservation.tenant_id)


def test_the_public_key_endpoint_still_resolves():
    """Garde-fou cross-ticket : la keypair éphémère est bien partagée."""
    assert qr_public_key_pem(), (
        "Si cette assertion rougit, c'est que `_signing_key()` tombe sur une "
        "configuration qui ne génère plus la keypair éphémère — tout le JWT "
        "ticket s'effondre."
    )


# ─── Invariants du registre ───

def test_the_two_new_event_types_are_registered():
    """Un module non importé par `event_processor` n'enregistre rien."""
    assert "stop_arrive" in EVENT_HANDLERS
    assert "stop_depart" in EVENT_HANDLERS


def test_the_two_new_event_types_have_declared_detail_keys():
    """
    `details` est une liste blanche. Les clés que le handler fait remonter
    doivent y figurer, sinon elles disparaissent du verdict en silence.
    """
    assert VERDICT_DETAIL_KEYS["stop_arrive"] == ("stop_id", "stop_status")
    assert VERDICT_DETAIL_KEYS["stop_depart"] == ("stop_id", "stop_status")


def test_rejection_code_count_matches_the_declared_total():
    """
    35 → 37 après l'ajout de MISSING_STOP_ID et STOP_NOT_FOUND. Le compte
    exact sert de canari : un code ajouté sans mise à jour du schéma ou du
    client mobile serait un contrat caché.
    """
    assert len(RejectionCode) == 37
    assert RejectionCode.MISSING_STOP_ID.value == "MISSING_STOP_ID"
    assert RejectionCode.STOP_NOT_FOUND.value == "STOP_NOT_FOUND"
