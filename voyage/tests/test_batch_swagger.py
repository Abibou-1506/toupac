"""
TOUPAC Voyage — Le Swagger du batch offline ne ment pas.

Deux garanties se croisent ici :

- **Les 28 codes de rejet apparaissent dans l'énumération publiée.** Un code
  ajouté à `RejectionCode` sans qu'il remonte au schéma deviendrait un contrat
  caché : l'app mobile le recevrait sans savoir qu'il existe.
- **Les exemples décrivent ce que les handlers acceptent réellement.** Un
  exemple de documentation qui échouerait au contrôle du handler serait un
  piège : il ferait croire au dev que son code marche.

Le second test fait tourner chaque exemple contre son handler, pas une
comparaison statique de clés : rien n'empêche un dev d'ajouter une clé au
handler sans l'exposer dans le payload lu, et un test d'inclusion de clés
laisserait passer. Faire tourner le handler attrape ce cas, et vérifie du même
coup que l'exemple ne finira pas en rejet silencieux.
"""
import uuid
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.utils import timezone

from geo.models import Place
from iam.models import Tenant, User
from voyage.models import (
    Anomaly,
    Controller,
    ControlSession,
    Reservation,
    Route,
    RouteStop,
    SeatMap,
    Trip,
)
from voyage.schema_examples import REQUEST_EXAMPLES, RESPONSE_EXAMPLES
from voyage.services.event_processor import EVENT_HANDLERS, BatchEventProcessor
from voyage.services.exceptions import RejectionCode

pytestmark = pytest.mark.django_db


# ─── Décor minimal : un voyage, un siège libre, un contrôleur ───
#
# Les exemples visent le siège A1 et un `parcel_id` factice ; les fixtures
# montent de quoi faire traverser la chaîne complète sans tomber sur un rejet
# qui dirait « exemple incomplet » quand ce serait « décor incomplet ».

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Swagger", slug="swagger-batch")


@pytest.fixture
def controller(tenant):
    user = User.objects.create_user(
        email="ctrl@swagger-batch.sn", password="TestPass#2026",
        first_name="Moussa", last_name="Sarr",
        tenant=tenant, role=User.Role.CONTROLLER,
    )
    return Controller.objects.create(tenant=tenant, user=user, matricule="CH-S01")


@pytest.fixture
def trip(tenant):
    """Voyage en préparation : accepte la transition `boarding` de l'exemple."""
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.9246, 14.7886, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS",
        origin_place=origin, destination_place=destination,
    )
    seat_map = SeatMap.objects.create(
        tenant=tenant, name="Grille 2x3", total_seats=6,
        layout={"rows": 2, "cols": 3},
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-001",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=6, seat_map=seat_map, status=Trip.Status.PREPARING,
    )


@pytest.fixture
def session(tenant, controller, trip):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller,
        device_id="DEVICE-S01", opened_at=timezone.now(),
    )


# ─── L'énumération entière est publiée ───

def test_the_schema_lists_every_rejection_code():
    """
    Un code ajouté à `RejectionCode` doit apparaître dans le schéma publié.

    Appel du générateur de drf-spectacular directement — l'alternative serait
    d'écrire le fichier avec `spectacular --file`, dépendant du système de
    fichiers, du cache et de l'ordre d'exécution des tests.
    """
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)

    enum = schema["components"]["schemas"]["RejectionCodeEnum"]["enum"]
    expected = {code.value for code in RejectionCode}
    assert set(enum) == expected, (
        "Dérive entre `RejectionCode` et le schéma publié. "
        f"Dans l'énum, absent du schéma : {expected - set(enum)}. "
        f"Dans le schéma, absent de l'énum : {set(enum) - expected}."
    )
    assert len(enum) == 35, (
        "Le compte a bougé : hardening a figé 28 valeurs, le ticket vente à "
        "bord sur trajet partiel en a ajouté 7 (stops), total 35. En changer "
        "impose un ticket produit, pas une révision mécanique de ce test."
    )


# ─── Un exemple par event_type, chacun aligné sur son handler ───

def test_every_handler_has_a_request_example():
    """
    Un `event_type` sans exemple est un `event_type` que personne ne pourra
    utiliser en lisant le Swagger. L'oubli doit être rouge, pas silencieux.
    """
    assert set(REQUEST_EXAMPLES) == set(EVENT_HANDLERS)


def test_two_response_examples_are_published():
    """Un verdict accepté enrichi, un verdict rejeté — le minimum pour couvrir
    les deux formes que l'app doit savoir lire."""
    assert len(RESPONSE_EXAMPLES) >= 2
    statuses = [
        example.value["results"][0]["status"] for example in RESPONSE_EXAMPLES
    ]
    assert "accepted" in statuses
    assert "rejected" in statuses


def _event_from_example(event_type):
    """L'event unique porté par l'exemple d'entrée, prêt à être traité."""
    return REQUEST_EXAMPLES[event_type].value["events"][0]


@pytest.fixture
def live_targets(tenant, controller, session, trip):
    """
    Les cibles concrètes que les exemples désignent par UUID factice.

    Les exemples portent des identifiants volontairement factices (pour ne pas
    laisser croire à des IDs de production). On monte ici une réservation, une
    anomalie et un colis réels, et on rend un dict `{factice → vrai}` qui sert
    à patcher les payloads au moment de leur exécution. C'est le seul endroit
    où les deux mondes se rejoignent — l'exemple reste un littéral pur, le
    décor reste un décor Django.
    """
    from colis.models import Order, Parcel
    from voyage.models import Passenger

    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop", phone="+221770000111",
    )
    reservation = Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger,
        seat_label="A1", status=Reservation.Status.BOOKED, amount_xof=10000,
    )
    anomaly = Anomaly.objects.create(
        tenant=tenant, session=session,
        type=Anomaly.Type.OTHER, severity=Anomaly.Severity.LOW, title="À clôturer",
    )
    pickup = Place.objects.create(
        tenant=tenant, name="Retrait", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    dropoff = Place.objects.create(
        tenant=tenant, name="Livraison", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    order = Order.objects.create(
        tenant=tenant, internal_id="CMD-S01",
        pickup_place=pickup, dropoff_place=dropoff,
        status=Order.Status.CONFIRMED, total_amount_xof=5000,
        priority=Order.Priority.STANDARD,
        payment_status=Order.PaymentStatus.PENDING,
    )
    parcel = Parcel.objects.create(
        tenant=tenant, order=order, tracking_number="TRK-S01",
        description="Carton", weight_kg=2, status=Parcel.Status.CREATED,
    )
    # Deux `RouteStop` sur la route du trip, ordonnés et autorisés en
    # embarquement/descente — nécessaires depuis que l'exemple `onboard_sale`
    # inclut `origin_stop` / `destination_stop`. Les positions 1 et 2 ne
    # chevauchent pas l'origine/destination de la route (déjà aux positions 0
    # et max par convention).
    origin_stop = RouteStop.objects.create(
        tenant=tenant, route=trip.route, place=pickup, stop_order=1,
        is_boarding=True, is_alighting=True,
    )
    destination_stop = RouteStop.objects.create(
        tenant=tenant, route=trip.route, place=dropoff, stop_order=2,
        is_boarding=True, is_alighting=True,
    )
    return {
        # Clés visitées récursivement dans `payload` : factice → réel.
        "trip_id": str(trip.pk),
        "reservation_id": str(reservation.pk),
        "anomaly_id": str(anomaly.pk),
        "parcel_id": str(parcel.pk),
        "boarded_by_controller_id": str(controller.pk),
        "origin_stop": str(origin_stop.pk),
        "destination_stop": str(destination_stop.pk),
    }


def _substitute(value, mapping):
    """
    Remplace, dans un dict/liste imbriqué, chaque valeur dont la clé figure dans
    `mapping`. L'exemple d'origine reste intact — on recopie à la volée.
    """
    if isinstance(value, dict):
        return {
            key: (mapping[key] if key in mapping else _substitute(sub, mapping))
            for key, sub in value.items()
        }
    if isinstance(value, list):
        return [_substitute(item, mapping) for item in value]
    return value


@pytest.fixture
def seeded_templates():
    """Templates `notif.*` seedés — certains handlers émettent in-app."""
    call_command("seed_notification_templates", stdout=StringIO())


@pytest.mark.parametrize("event_type", list(REQUEST_EXAMPLES))
def test_every_swagger_example_is_accepted_by_its_handler(
    event_type, tenant, controller, session, live_targets, seeded_templates,
):
    """
    Chaque exemple du Swagger traverse son handler sans rejet.

    L'alternative aurait été une comparaison statique entre les clés de
    `payload` et celles lues par le handler — moins coûteuse à monter, mais
    elle laisserait passer un exemple avec une valeur de mauvais type (un
    `payment_method` qui ne figure pas dans la liste blanche, un `to_status`
    hors graphe). Faire tourner le handler attrape ces cas-là.
    """
    event_data = _substitute(_event_from_example(event_type), live_targets)
    # Les identifiants d'event sont uniques par test : sans cela le second
    # parcours de la paramétrisation retomberait sur l'idempotence.
    event_data["client_uuid"] = str(uuid.uuid4())
    if event_data.get("target_id") in {live_targets["reservation_id"],
                                        live_targets["anomaly_id"],
                                        live_targets["parcel_id"]}:
        # `target_id` est déjà remplacé par le réel ; rien à faire.
        pass

    processor = BatchEventProcessor(
        session=session, tenant=tenant, user=controller.user,
    )
    verdict = processor.process_batch([event_data])[0]

    assert verdict["status"] == "accepted", (
        f"L'exemple Swagger pour `{event_type}` est rejeté par son handler : "
        f"code={verdict.get('rejection_code')!r}, "
        f"raison={verdict.get('rejection_reason')!r}. "
        "Soit le handler a changé sans mise à jour de "
        "`voyage/schema_examples.py`, soit l'exemple a été rédigé sans "
        "regarder le handler."
    )


def test_every_request_example_targets_a_known_event_type():
    """Un exemple pour un event_type qui n'existe plus ne servirait jamais."""
    assert set(REQUEST_EXAMPLES) <= set(EVENT_HANDLERS)
