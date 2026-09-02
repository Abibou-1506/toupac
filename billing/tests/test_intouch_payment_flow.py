"""
TOUPAC Billing — Flux de paiement Intouch et moteur de tarification.

Mock au niveau service (Option B) : c'est `IntouchProvider` qui est remplacé,
pas la couche HTTP. Note d'implémentation — `billing/views.py` importe
`IntouchProvider` DANS le corps des méthodes, pas au niveau module. Le nom
`billing.views.IntouchProvider` n'existe donc pas et ne peut pas être patché ;
on patche la classe à sa source, `billing.providers.intouch.IntouchProvider`,
que l'import local résout à chaque appel.
"""
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.utils import timezone

from billing.models import Payment, PriceList, PriceRule
from billing.providers.base import PaymentResult
from colis.models import Order
from geo.models import Place
from voyage.models import Passenger, Reservation, Route, Schedule, Trip

pytestmark = pytest.mark.django_db

INITIATE_URL = "/api/v1/billing/payments/initiate/"
WEBHOOK_URL = "/api/v1/billing/payments/webhook/"
PRICING_URL = "/api/v1/billing/pricing/calculate/"

PROVIDER_PATH = "billing.providers.intouch.IntouchProvider"


# ─── Fabriques ───

def make_route(tenant, code="DKR-BKO"):
    return Route.objects.create(
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


def make_reservation(tenant, seat_label="A1"):
    now = timezone.now()
    trip = Trip.objects.create(
        tenant=tenant, route=make_route(tenant, f"R{seat_label}"),
        internal_id=f"VYG-{seat_label}", departure_date=now.date(),
        scheduled_at=now, total_seats=45,
    )
    passenger = Passenger.objects.create(tenant=tenant, first_name="Awa", last_name="Diop")
    return Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger,
        seat_label=seat_label, amount_xof=8500, status=Reservation.Status.BOOKED,
    )


def make_order(tenant, internal_id="CMD-001"):
    return Order.objects.create(
        tenant=tenant, internal_id=internal_id, customer_name="Client",
        pickup_place=Place.objects.create(
            tenant=tenant, name="Retrait", type=Place.PlaceType.STATION,
            location=Point(-17.4, 14.7, srid=4326),
        ),
        dropoff_place=Place.objects.create(
            tenant=tenant, name="Livraison", type=Place.PlaceType.STATION,
            location=Point(-8.0, 12.6, srid=4326),
        ),
    )


def provider_mock(initiate=None, verify=True, tx_status="success"):
    """Instance mockée d'IntouchProvider, prête à être renvoyée par le patch."""
    instance = mock.Mock()
    instance.initiate_payment.return_value = initiate or PaymentResult(
        success=True, provider_tx_id="TEST-TX-001", redirect_url="", raw_response={"ok": True},
    )
    instance.verify_callback.return_value = verify
    instance.get_transaction_status.return_value = tx_status
    return instance


def initiate_body(reservation_id, **overrides):
    body = {
        "provider": "wave",
        "amount_xof": 8500,
        "customer_phone": "+221771234567",
        "reservation_id": str(reservation_id),
    }
    body.update(overrides)
    return body


# ─── Initiate ───

def test_initiate_payment_success_creates_payment_pending(authenticated_client, user_admin_a, tenant_a):
    reservation = make_reservation(tenant_a)

    with mock.patch(PROVIDER_PATH, return_value=provider_mock()):
        response = authenticated_client(user_admin_a).post(
            INITIATE_URL, initiate_body(reservation.id), format="json",
        )

    assert response.status_code == 201, response.data
    assert response.data["status"] == "pending"
    assert response.data["provider_tx_id"] == "TEST-TX-001"
    assert response.data["payment_id"]

    payment = Payment.objects.get(id=response.data["payment_id"])
    assert payment.status == Payment.Status.PENDING
    assert payment.tenant_id == tenant_a.id
    assert payment.amount_xof == 8500
    assert payment.provider_tx_id == "TEST-TX-001"


def test_initiate_payment_failure_records_failed_payment(authenticated_client, user_admin_a, tenant_a):
    reservation = make_reservation(tenant_a)
    failure = PaymentResult(success=False, error_message="Insufficient funds")

    with mock.patch(PROVIDER_PATH, return_value=provider_mock(initiate=failure)):
        response = authenticated_client(user_admin_a).post(
            INITIATE_URL, initiate_body(reservation.id), format="json",
        )

    assert response.status_code == 400, response.data
    assert response.data["status"] == "failed"
    assert "Insufficient funds" in response.data["error"]

    payment = Payment.objects.get(id=response.data["payment_id"])
    assert payment.status == Payment.Status.FAILED
    assert "Insufficient funds" in payment.failure_reason


def test_initiate_payment_scoped_to_current_tenant(
    authenticated_client, user_admin_a, tenant_a, tenant_b,
):
    """
    Comportement OBSERVÉ : fail-open sur reservation_id.

    Le Payment est bien créé dans tenant_a (imposé par `request.tenant`), mais
    `reservation_id` n'est validé contre aucun tenant — il pointe vers une
    réservation de tenant_b, inaccessible à l'utilisateur. Un webhook ultérieur
    marquerait donc cette réservation de tenant_b comme checked_in.
    TODO : PaymentInitiateSerializer devrait valider reservation_id/order_id
    contre `request.tenant`.
    """
    reservation_b = make_reservation(tenant_b, seat_label="B1")

    with mock.patch(PROVIDER_PATH, return_value=provider_mock()):
        response = authenticated_client(user_admin_a).post(
            INITIATE_URL, initiate_body(reservation_b.id), format="json",
        )

    assert response.status_code == 201, response.data
    payment = Payment.objects.get(id=response.data["payment_id"])
    assert payment.tenant_id == tenant_a.id
    assert payment.reservation_id == reservation_b.id


def test_initiate_payment_requires_authentication(api_client, tenant_a):
    reservation = make_reservation(tenant_a)

    with mock.patch(PROVIDER_PATH, return_value=provider_mock()):
        response = api_client.post(INITIATE_URL, initiate_body(reservation.id), format="json")

    assert response.status_code == 401


def test_initiate_payment_throttled_after_30_per_minute(
    authenticated_client, user_admin_a, tenant_a,
):
    reservation = make_reservation(tenant_a)
    rates = {"auth_login": "10/minute", "batch_sync": "20/minute",
             "payment_initiate": "30/minute", "tenant_burst": "100/minute"}
    client = authenticated_client(user_admin_a)

    with (
        mock.patch(PROVIDER_PATH, return_value=provider_mock()),
        override_settings(REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework_simplejwt.authentication.JWTAuthentication",
                "rest_framework.authentication.SessionAuthentication",
            ],
            "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
            "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
            "DEFAULT_THROTTLE_RATES": rates,
        }),
    ):
        statuses = [
            client.post(INITIATE_URL, initiate_body(reservation.id), format="json").status_code
            for _ in range(31)
        ]

    assert statuses[:30] == [201] * 30
    assert statuses[30] == 429


# ─── Webhook ───

def test_webhook_marks_payment_success_and_updates_reservation(api_client, tenant_a):
    reservation = make_reservation(tenant_a)
    payment = Payment.objects.create(
        tenant=tenant_a, provider="wave", amount_xof=8500,
        reservation_id=reservation.id, provider_tx_id="TX-999",
        status=Payment.Status.PENDING,
    )

    with mock.patch(PROVIDER_PATH, return_value=provider_mock(verify=True, tx_status="success")):
        response = api_client.post(
            WEBHOOK_URL, {"partner_transaction_id": "TX-999"}, format="json",
        )

    assert response.status_code == 200, response.data
    assert response.data == {"status": "received"}

    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCESS
    assert payment.completed_at is not None

    reservation.refresh_from_db()
    assert reservation.status == Reservation.Status.CHECKED_IN
    assert reservation.payment_ref == "TX-999"


def test_webhook_marks_payment_success_and_updates_order(api_client, tenant_a):
    order = make_order(tenant_a)
    payment = Payment.objects.create(
        tenant=tenant_a, provider="wave", amount_xof=5000,
        order_id=order.id, provider_tx_id="TX-ORDER-1",
        status=Payment.Status.PENDING,
    )

    with mock.patch(PROVIDER_PATH, return_value=provider_mock(verify=True, tx_status="success")):
        response = api_client.post(
            WEBHOOK_URL, {"partner_transaction_id": "TX-ORDER-1"}, format="json",
        )

    assert response.status_code == 200, response.data
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCESS

    order.refresh_from_db()
    assert order.payment_status == "paid"


def test_webhook_rejects_invalid_signature(api_client):
    with mock.patch(PROVIDER_PATH, return_value=provider_mock(verify=False)):
        response = api_client.post(
            WEBHOOK_URL, {"partner_transaction_id": "TX-999"}, format="json",
        )

    assert response.status_code == 403


def test_webhook_returns_404_for_unknown_provider_tx_id(api_client):
    with mock.patch(PROVIDER_PATH, return_value=provider_mock(verify=True)):
        response = api_client.post(
            WEBHOOK_URL, {"partner_transaction_id": "TX-INEXISTANT"}, format="json",
        )

    assert response.status_code == 404


def test_webhook_records_failure_on_failed_status(api_client, tenant_a):
    reservation = make_reservation(tenant_a)
    payment = Payment.objects.create(
        tenant=tenant_a, provider="wave", amount_xof=8500,
        reservation_id=reservation.id, provider_tx_id="TX-FAIL",
        status=Payment.Status.PENDING,
    )

    with mock.patch(PROVIDER_PATH, return_value=provider_mock(verify=True, tx_status="failed")):
        response = api_client.post(
            WEBHOOK_URL,
            {"partner_transaction_id": "TX-FAIL", "message": "Solde insuffisant"},
            format="json",
        )

    assert response.status_code == 200, response.data
    payment.refresh_from_db()
    assert payment.status == Payment.Status.FAILED
    assert payment.failure_reason == "Solde insuffisant"

    reservation.refresh_from_db()
    assert reservation.status == Reservation.Status.BOOKED


# ─── Moteur de tarification ───

def test_pricing_calculate_voyage_uses_pricelist_if_present(
    authenticated_client, user_admin_a, tenant_a,
):
    route = make_route(tenant_a)
    price_list = PriceList.objects.create(
        tenant=tenant_a, name="Tarifs voyage", type=PriceList.Type.VOYAGE, is_active=True,
    )
    PriceRule.objects.create(
        tenant=tenant_a, price_list=price_list, route=route,
        calculation_method=PriceRule.CalculationMethod.FIXED, base_amount_xof=7500,
    )

    response = authenticated_client(user_admin_a).post(
        PRICING_URL, {"type": "voyage", "route_id": str(route.id)}, format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["price_xof"] == 7500


def test_pricing_calculate_voyage_falls_back_to_schedule_default_price(
    authenticated_client, user_admin_a, tenant_a,
):
    route = make_route(tenant_a)
    Schedule.objects.create(
        tenant=tenant_a, route=route, departure_time="08:00",
        days_of_week=[0, 1, 2, 3, 4], default_price_xof=6000, is_active=True,
    )

    response = authenticated_client(user_admin_a).post(
        PRICING_URL, {"type": "voyage", "route_id": str(route.id)}, format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["price_xof"] == 6000


def test_pricing_calculate_returns_400_when_no_price_configured(
    authenticated_client, user_admin_a, tenant_a,
):
    route = make_route(tenant_a)

    response = authenticated_client(user_admin_a).post(
        PRICING_URL, {"type": "voyage", "route_id": str(route.id)}, format="json",
    )

    assert response.status_code == 400, response.data
    assert response.data["detail"] == "Aucun tarif configuré"
