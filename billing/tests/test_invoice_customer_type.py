"""
TOUPAC Billing — `InvoiceGenerator` respecte la convention `customer_type`.

Le couple `(customer_id, customer_type)` d'`Invoice` est une référence
polymorphe sans clé étrangère : lire `customer_id` sans vérifier `customer_type`
reviendrait à prendre l'identifiant d'un client externe pour celui d'un compte
TOUPAC — exactement ce que `/customer/my-payments/` protège par son filtre.

Jusqu'au 1er oct 2026, `from_reservation` écrivait `"passenger"` dans tous les
cas et `from_order` écrivait `"user"` — deux valeurs qui n'appartenaient à
aucune branche de la convention. Un client qui avait réservé et payé ne
retrouvait aucun de ses règlements dans son espace. Les tests ci-dessous
figent le contrat.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from billing.models import (
    CUSTOMER_TYPE_CLIENT_USER,
    CUSTOMER_TYPE_EXTERNAL,
    CUSTOMER_TYPE_PASSENGER,
    Payment,
)
from billing.services import InvoiceGenerator
from colis.models import Order
from geo.models import Place
from iam.models import Tenant, User
from voyage.models import Passenger, Reservation, Route, Trip

pytestmark = pytest.mark.django_db


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Fact", slug="billing-conv")


@pytest.fixture
def client_user():
    user, _ = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000101",
        first_name="Fatou", last_name="Mbaye",
    )
    return user


@pytest.fixture
def trip(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Thiès", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Thiès", code="DKR-THS",
        origin_place=origin, destination_place=destination,
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-F01",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45,
    )


def _reservation(tenant, trip, *, customer_user=None, seat="A1"):
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Awa", last_name="Diop",
        phone=f"+22177000{seat:>04}", customer_user=customer_user,
    )
    return Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger, seat_label=seat,
        status=Reservation.Status.BOARDED, amount_xof=10000,
    )


# ─── from_reservation ───

def test_a_reservation_with_a_linked_passenger_bills_the_client_account(
    tenant, trip, client_user,
):
    """
    Le cas qui faisait disparaître les paiements : le passager était rattaché
    au compte client, mais la facture pointait sur la fiche passager.
    """
    reservation = _reservation(tenant, trip, customer_user=client_user)

    invoice = InvoiceGenerator.from_reservation(reservation)

    assert invoice.customer_type == CUSTOMER_TYPE_CLIENT_USER
    assert invoice.customer_id == client_user.id


def test_a_reservation_without_a_linked_passenger_bills_the_passenger_record(
    tenant, trip,
):
    """
    Un voyageur occasionnel sans compte reste identifié par sa fiche
    passager — un `customer_id` de ce type ne coïncide pas avec un `User.pk`.
    """
    reservation = _reservation(tenant, trip, customer_user=None)

    invoice = InvoiceGenerator.from_reservation(reservation)

    assert invoice.customer_type == CUSTOMER_TYPE_PASSENGER
    assert invoice.customer_id == reservation.passenger_id


def test_my_payments_sees_the_client_user_invoice_and_hides_the_passenger_one(
    tenant, trip, client_user,
):
    """
    Bout en bout : la vue `/customer/my-payments/` et le `from_reservation`
    nouveau se parlent, et les factures « passenger » restent correctement
    hors de portée du compte client.
    """
    from rest_framework.test import APIClient

    from iam.serializers import ToupacTokenObtainSerializer

    linked = _reservation(tenant, trip, customer_user=client_user, seat="A1")
    orphan = _reservation(tenant, trip, customer_user=None, seat="A2")

    linked_invoice = InvoiceGenerator.from_reservation(linked)
    orphan_invoice = InvoiceGenerator.from_reservation(orphan)

    Payment.objects.create(
        tenant=tenant, invoice=linked_invoice, provider=Payment.Provider.WAVE,
        amount_xof=10000, status=Payment.Status.SUCCESS,
    )
    Payment.objects.create(
        tenant=tenant, invoice=orphan_invoice, provider=Payment.Provider.CASH,
        amount_xof=10000, status=Payment.Status.SUCCESS,
    )

    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(client_user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.get("/api/v1/customer/my-payments/")

    assert response.status_code == 200, response.data
    payments = response.data["payments"]
    assert len(payments) == 1
    # Un seul paiement ressort : celui de la facture rattachée au client.
    # Celui du passager anonyme reste invisible — bon comportement de la
    # convention polymorphe.


# ─── from_order ───

@pytest.fixture
def order_places(tenant):
    pickup = Place.objects.create(
        tenant=tenant, name="Retrait", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    dropoff = Place.objects.create(
        tenant=tenant, name="Livraison", type=Place.PlaceType.STATION,
        location=Point(-16.92, 14.78, srid=4326),
    )
    return pickup, dropoff


def _order(tenant, places, *, customer=None, name="Externe"):
    pickup, dropoff = places
    return Order.objects.create(
        tenant=tenant, internal_id=f"CMD-{'c' if customer else 'x'}",
        customer=customer, customer_name=name,
        pickup_place=pickup, dropoff_place=dropoff,
        status=Order.Status.DELIVERED, total_amount_xof=5000,
        priority=Order.Priority.STANDARD,
        payment_status=Order.PaymentStatus.PAID,
    )


def test_an_order_with_a_customer_bills_the_client_account(
    tenant, order_places, client_user,
):
    """
    Avant correctif : `customer_type="user"` — valeur ignorée par toute
    lecture, le client ne voyait pas son règlement.
    """
    order = _order(tenant, order_places, customer=client_user, name="Fatou Mbaye")

    invoice = InvoiceGenerator.from_order(order)

    assert invoice.customer_type == CUSTOMER_TYPE_CLIENT_USER
    assert invoice.customer_id == client_user.id


def test_an_order_without_a_customer_bills_as_external_with_a_null_id(
    tenant, order_places,
):
    """
    Un expéditeur anonyme (coordonnées texte seules) n'a pas d'identifiant
    exploitable depuis l'espace client. `customer_id` reste **nul** —
    l'ancien code recopiait `order.customer_id` quand même, ce qui pouvait
    être pris pour un identifiant valide.
    """
    order = _order(tenant, order_places, customer=None, name="Monsieur X")

    invoice = InvoiceGenerator.from_order(order)

    assert invoice.customer_type == CUSTOMER_TYPE_EXTERNAL
    assert invoice.customer_id is None


# ─── Invariant : seules les trois valeurs documentées sont écrites ───

def test_invoice_generator_only_writes_the_three_declared_types(
    tenant, trip, client_user, order_places,
):
    """
    Un code qui écrirait `"passenger"` ou `"user"` (anciennes valeurs) le
    ferait silencieusement passer la lecture. Ce test fait tourner les deux
    méthodes dans toutes leurs branches et vérifie que seules les trois
    valeurs constantes sortent.
    """
    allowed = {
        CUSTOMER_TYPE_CLIENT_USER, CUSTOMER_TYPE_PASSENGER, CUSTOMER_TYPE_EXTERNAL,
    }

    InvoiceGenerator.from_reservation(
        _reservation(tenant, trip, customer_user=client_user, seat="A1"),
    )
    InvoiceGenerator.from_reservation(
        _reservation(tenant, trip, customer_user=None, seat="A2"),
    )
    InvoiceGenerator.from_order(_order(tenant, order_places, customer=client_user))
    InvoiceGenerator.from_order(_order(tenant, order_places, customer=None))

    from billing.models import Invoice

    produced = set(Invoice.objects.values_list("customer_type", flat=True))
    assert produced == allowed
