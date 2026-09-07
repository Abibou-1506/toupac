"""Fabriques métier minimales pour les tests des endpoints client.

Construire une réservation demande une chaîne complète — lieu, route, horaire,
véhicule, voyage, passager. Ces helpers la montent avec le strict nécessaire,
pour que les tests parlent de ce qu'ils vérifient et pas du décor.
"""
from datetime import date, timedelta

from django.contrib.gis.geos import Point
from django.utils import timezone

from billing.models import CUSTOMER_TYPE_CLIENT_USER, Invoice, Payment
from colis.models import Order
from geo.models import Place
from voyage.models import Passenger, Reservation, Route, Trip

_counter = {"n": 0}


def _next():
    _counter["n"] += 1
    return _counter["n"]


def make_place(tenant, name="Dakar"):
    return Place.objects.create(
        tenant=tenant, name=f"{name}-{_next()}", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )


def make_trip(tenant, departure_date=None, route_name="Dakar → Bamako"):
    route = Route.objects.create(
        tenant=tenant, name=route_name, code=f"R{_next():03d}",
        origin_place=make_place(tenant), destination_place=make_place(tenant, "Bamako"),
        distance_km=1200, duration_minutes=900,
    )
    departure_date = departure_date or date.today() + timedelta(days=7)
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id=f"TRP-{_next():04d}",
        departure_date=departure_date,
        scheduled_at=timezone.now() + timedelta(days=7),
        status=Trip.Status.SCHEDULED, total_seats=45, booked_seats=0,
    )


def make_reservation(tenant, customer_user=None, trip=None, **overrides):
    """Une réservation complète. `customer_user=None` produit un passager invité."""
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Fatou", last_name=f"Mbaye{_next()}",
        phone="+221770000001", nationality="SN", customer_user=customer_user,
    )
    payload = {
        "tenant": tenant,
        "trip": trip or make_trip(tenant),
        "passenger": passenger,
        "seat_label": f"A{_next()}",
        "status": Reservation.Status.BOOKED,
        "amount_xof": 15000,
    }
    return Reservation.objects.create(**{**payload, **overrides})


def make_order(tenant, customer=None, **overrides):
    payload = {
        "tenant": tenant,
        "internal_id": f"CMD-{_next():05d}",
        "customer": customer,
        "customer_name": "Fatou Mbaye",
        "customer_phone": "+221770000001",
        "pickup_place": make_place(tenant, "Retrait"),
        "dropoff_place": make_place(tenant, "Livraison"),
        "status": Order.Status.CONFIRMED,
        "total_amount_xof": 5000,
        "priority": Order.Priority.STANDARD,
        "payment_status": Order.PaymentStatus.PENDING,
    }
    return Order.objects.create(**{**payload, **overrides})


def make_invoice(tenant, customer_id=None, customer_type=CUSTOMER_TYPE_CLIENT_USER):
    return Invoice.objects.create(
        tenant=tenant, invoice_number=f"FAC-{_next():05d}",
        customer_id=customer_id, customer_type=customer_type,
        customer_name="Fatou Mbaye", issue_date=date.today(),
        subtotal_xof=15000, tax_xof=0, total_xof=15000,
    )


def make_payment(tenant, order=None, invoice=None, reservation=None, **overrides):
    payload = {
        "tenant": tenant, "order": order, "invoice": invoice, "reservation": reservation,
        "provider": "intouch", "amount_xof": 15000,
        "status": Payment.Status.SUCCESS,
        "initiated_at": timezone.now(),
    }
    return Payment.objects.create(**{**payload, **overrides})
