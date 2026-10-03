"""Tests des badges statut dans les ModelAdmin métier (Ticket 3, C1).

Un test par admin avec statut qui vérifie que la classe CSS Tailwind
sémantique est bien rendue dans le changelist. Assertion sur l'attribut
(`bg-warning-50` par ex.) et non sur le libellé — les labels FR
traversent `escape` HTML (DECISIONS.md « assertions sur URL/attributs »).
"""
import pytest
from django.test import Client
from django.urls import reverse

from billing.models import Payment
from colis.models import Order
from iam.tests.customer_factories import make_order, make_payment, make_trip
from voyage.models import Anomaly, ControlEvent, Controller, ControlSession, Incident, Reservation


@pytest.mark.django_db
def test_order_admin_renders_status_badge(superadmin, tenant_a):
    """Un order confirmed → badge primary (bleu)."""
    make_order(tenant_a, status=Order.Status.CONFIRMED)
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:colis_order_changelist"))
    assert response.status_code == 200
    assert "bg-primary-50" in response.content.decode()


@pytest.mark.django_db
def test_order_admin_renders_warning_badge_for_in_transit(superadmin, tenant_a):
    """Un order in_transit → badge warning (orange)."""
    make_order(tenant_a, status=Order.Status.IN_TRANSIT)
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:colis_order_changelist"))
    assert "bg-warning-50" in response.content.decode()


@pytest.mark.django_db
def test_payment_admin_renders_success_badge(superadmin, tenant_a):
    """Un payment success → badge success (vert)."""
    from django.utils import timezone
    make_payment(tenant_a, status=Payment.Status.SUCCESS, completed_at=timezone.now())
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:billing_payment_changelist"))
    assert "bg-success-50" in response.content.decode()


@pytest.mark.django_db
def test_payment_admin_renders_danger_badge_for_failed(superadmin, tenant_a):
    """Un payment failed → badge danger (rouge)."""
    make_payment(tenant_a, status=Payment.Status.FAILED)
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:billing_payment_changelist"))
    assert "bg-danger-50" in response.content.decode()


@pytest.mark.django_db
def test_trip_admin_renders_status_badge(superadmin, tenant_a):
    """Un trip scheduled → badge primary (bleu)."""
    make_trip(tenant_a)  # default Status.SCHEDULED
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:voyage_trip_changelist"))
    assert response.status_code == 200
    assert "bg-primary-50" in response.content.decode()


@pytest.mark.django_db
def test_incident_admin_renders_status_badge(superadmin, user_admin_a, tenant_a):
    """Un incident reported → badge danger (rouge)."""
    trip = make_trip(tenant_a)
    Incident.objects.create(
        tenant=tenant_a, trip=trip, reporter=user_admin_a,
        type=Incident.Type.OTHER, severity=Incident.Severity.LOW,
        title="x", status=Incident.Status.REPORTED,
    )
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:voyage_incident_changelist"))
    assert "bg-danger-50" in response.content.decode()


@pytest.mark.django_db
def test_reservation_admin_renders_status_badge(superadmin, tenant_a):
    """Une réservation booked → badge warning (checked_in warning fallback)
    ou primary selon mapping."""
    from voyage.models import Passenger
    trip = make_trip(tenant_a)
    passenger = Passenger.objects.create(
        tenant=tenant_a, first_name="X", last_name="Y", phone="+221770000001",
        nationality="SN",
    )
    Reservation.objects.create(
        tenant=tenant_a, trip=trip, passenger=passenger,
        seat_label="A1", amount_xof=5000, status=Reservation.Status.CANCELLED,
    )
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:voyage_reservation_changelist"))
    assert response.status_code == 200
    # Reservation.CANCELLED mappé en danger.
    assert "bg-danger-50" in response.content.decode()


@pytest.mark.django_db
def test_anomaly_admin_renders_status_badge(superadmin, user_admin_a, tenant_a):
    """Une anomaly to_treat → danger."""
    controller = Controller.objects.create(
        tenant=tenant_a, user=user_admin_a, matricule="CTRL-X",
    )
    trip = make_trip(tenant_a)
    session = ControlSession.objects.create(
        tenant=tenant_a, trip=trip, controller=controller,
        opened_at="2026-10-02T10:00:00Z",
    )
    Anomaly.objects.create(
        tenant=tenant_a, session=session,
        type=Anomaly.Type.OTHER, severity=Anomaly.Severity.LOW,
        status=Anomaly.Status.TO_TREAT, title="x",
    )
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:voyage_anomaly_changelist"))
    assert "bg-danger-50" in response.content.decode()


@pytest.mark.django_db
def test_controlevent_admin_renders_status_badge(superadmin, user_admin_a, tenant_a):
    """Un control event pending → warning."""
    import uuid

    from django.utils import timezone
    controller = Controller.objects.create(
        tenant=tenant_a, user=user_admin_a, matricule="CTRL-Y",
    )
    trip = make_trip(tenant_a)
    session = ControlSession.objects.create(
        tenant=tenant_a, trip=trip, controller=controller,
        opened_at=timezone.now(),
    )
    ControlEvent.objects.create(
        tenant=tenant_a, session=session, client_uuid=uuid.uuid4(),
        event_type="boarding", created_at_local=timezone.now(),
        status=ControlEvent.Status.PENDING,
    )
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:voyage_controlevent_changelist"))
    assert "bg-warning-50" in response.content.decode()
