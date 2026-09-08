"""
TOUPAC Notifications — Les événements atteignent vraiment leurs destinataires.

Les tests par resolver vérifient chacun sa résolution isolément. Ceux-ci
vérifient le raccordement complet : un `emit()` réel, sans substitution, qui
part d'un contexte métier et arrive à des lignes en base.

C'est ce qui distingue « vingt-neuf fonctions écrites » de « les notifications
partent ». Aucun `temporary_resolver` ici : il sert à substituer un resolver,
pas à éprouver celui qui est réellement enregistré.
"""
import pytest

from notifications.catalog import all_events
from notifications.models import Notification, NotificationLog
from notifications.resolvers.base import (
    KNOWN_UNIMPLEMENTED_RESOLVERS,
    all_resolver_keys,
)
from notifications.services import NotificationService
from notifications.tests.emit_helpers import make_templates_for_all_channels

pytestmark = pytest.mark.django_db


# ─── Les invariants du registre ───

def test_no_catalog_resolver_is_left_unimplemented():
    """Le but du ticket, exprimé en une assertion."""
    assert KNOWN_UNIMPLEMENTED_RESOLVERS == frozenset()


def test_every_catalog_resolver_key_is_registered():
    declared = {event.resolver_key for event in all_events()}

    assert declared <= all_resolver_keys()


def test_every_resolver_module_is_imported_by_the_app():
    """
    Un module non importé dans `apps.py::ready()` n'enregistre rien.

    Le symptôme serait un `resolver_missing:` en production, et rien avant.
    """
    assert len(all_resolver_keys()) >= 29 + 2  # les 29 métier + les 2 exemples


# ─── Trois familles, bout en bout ───

def test_a_ticket_reaches_its_traveller(tenant_a, client_fatou):
    """
    TKT-01 — de la réservation au centre d'alertes du voyageur.

    Le client est global : c'est le lien passager qui porte l'isolation.
    """
    from django.utils import timezone

    from iam.tests.customer_factories import make_reservation

    reservation = make_reservation(tenant_a, customer_user=client_fatou)
    make_templates_for_all_channels("notif.ticket.issued.v1")

    result = NotificationService.emit(
        event_code="notif.ticket.issued.v1",
        context={
            "reservation_id": str(reservation.pk),
            "reference": "REF-001",
            "qr_payload": "QR-PAYLOAD",
            "route_label": "Dakar → Bamako",
            "departure_at": timezone.now(),
        },
        tenant=tenant_a,
    )

    assert result.skipped_no_recipient is False
    notification = Notification.objects.get()
    assert notification.recipient_user_id == client_fatou.pk
    assert notification.trigger_scope == "user"
    assert NotificationLog.objects.filter(user=client_fatou).exists()


def test_a_dispatch_assignment_reaches_the_driver(tenant_a, user_driver_a):
    """DSP-01 — un événement de personnel, résolu dans sa compagnie."""
    from django.utils import timezone

    make_templates_for_all_channels("notif.dispatch.assigned.v1")

    result = NotificationService.emit(
        event_code="notif.dispatch.assigned.v1",
        context={
            "driver_user_id": str(user_driver_a.pk),
            "assignment_id": str(user_driver_a.pk),
            "trip_code": "TRP-001",
            "route_label": "Dakar → Thiès",
            "departure_at": timezone.now(),
            "vehicle_label": "AA-123-BB",
        },
        tenant=tenant_a,
    )

    assert result.skipped_no_recipient is False
    assert Notification.objects.get().recipient_user_id == user_driver_a.pk


def test_the_parcel_pickup_code_reaches_the_recipient_not_the_sender(
    parcel_order, client_fatou, client_aicha, tenant_a,
):
    """
    COL-05 — le code de retrait, celui qui autorise à repartir avec le colis.

    Sans `Order.recipient_user`, livré par ce ticket, il n'avait aucun
    destinataire à résoudre : le code était rendu et n'atteignait personne.
    """
    make_templates_for_all_channels("notif.parcel.pickup_otp.v1")

    NotificationService.emit(
        event_code="notif.parcel.pickup_otp.v1",
        context={
            "order_id": str(parcel_order.pk),
            "tracking_number": "TRK-001",
            "otp": "482913",
            "expires_in_minutes": 30,
        },
        tenant=tenant_a,
    )

    recipients = set(
        Notification.objects.values_list("recipient_user_id", flat=True),
    )
    assert recipients == {client_aicha.pk}
    assert client_fatou.pk not in recipients


# ─── Le schéma de résolution ───

def test_a_missing_resolver_identifier_fails_loudly(tenant_a):
    """
    Un identifiant obligatoire absent lève à l'`emit()`.

    Sans cette validation, l'émission produirait une résolution vide que rien ne
    distinguerait d'un « personne à prévenir » légitime.
    """
    from django.utils import timezone

    with pytest.raises(ValueError, match="reservation_id"):
        NotificationService.emit(
            event_code="notif.ticket.issued.v1",
            context={
                "reference": "REF-001",
                "qr_payload": "QR",
                "route_label": "Dakar → Bamako",
                "departure_at": timezone.now(),
            },
            tenant=tenant_a,
        )


def test_a_resolver_identifier_must_be_a_uuid(tenant_a):
    from django.utils import timezone

    with pytest.raises(ValueError, match="reservation_id"):
        NotificationService.emit(
            event_code="notif.ticket.issued.v1",
            context={
                "reservation_id": "pas-un-uuid",
                "reference": "REF-001",
                "qr_payload": "QR",
                "route_label": "Dakar → Bamako",
                "departure_at": timezone.now(),
            },
            tenant=tenant_a,
        )


def test_an_optional_resolver_identifier_may_be_absent():
    """`compliance.responsible_and_driver` accepte un document sans chauffeur."""
    from django.utils import timezone

    from notifications.catalog import validate_context

    validate_context("notif.compliance.document_expiring.v1", {
        "document_type": "Assurance",
        "holder_label": "AA-123-BB",
        "expires_at": timezone.now(),
        "days_left": 30,
    })


def test_a_key_cannot_belong_to_both_schemas():
    """
    La même donnée servie par deux contrats divergerait au premier changement.

    L'erreur survient à la déclaration, donc au démarrage de l'application.
    """
    from notifications.catalog import NotifEvent, VariableSpec, register
    from notifications.channels import Channel
    from notifications.preferences import CATEGORY_TRIP_UPDATES
    from notifications.priorities import Priority

    with pytest.raises(ValueError, match="rendu et de résolution"):
        register(NotifEvent(
            code="notif.test.overlap.v1",
            charte_id="TST-01",
            label="Test",
            priority=Priority.LOW,
            category=CATEGORY_TRIP_UPDATES,
            default_channels=(Channel.IN_APP,),
            variables={"trip_id": VariableSpec(type="string")},
            resolver_variables={"trip_id": VariableSpec(type="uuid")},
            resolver_key="dispatch.dispatcher",
        ))


# ─── Coût en requêtes ───

def test_the_trip_resolver_stays_within_its_query_budget(
    django_assert_num_queries, trip_with_two_passengers, user_agent_a, tenant_a,
):
    """
    Canari, pas objectif : le nombre est celui qui a été observé.

    Une jointure ajoutée sans y penser le fera bouger, et c'est le seul moment
    où quelqu'un s'en apercevra.
    """
    from notifications.resolvers.base import get_resolver

    with django_assert_num_queries(3):
        get_resolver("trip.all_stakeholders")(
            {"trip_id": trip_with_two_passengers.trip.pk}, tenant_a,
        )


def test_the_parcel_resolver_stays_within_its_query_budget(
    django_assert_num_queries, parcel_order,
):
    from notifications.resolvers.base import get_resolver

    with django_assert_num_queries(1):
        get_resolver("parcel.sender_and_recipient")({"order_id": parcel_order.pk}, None)


def test_the_marketing_resolver_stays_within_its_query_budget(
    django_assert_num_queries, tenant_a, client_fatou,
):
    from iam.tests.customer_factories import make_reservation
    from notifications.resolvers.base import get_resolver

    make_reservation(tenant_a, customer_user=client_fatou)

    with django_assert_num_queries(1):
        get_resolver("marketing.consented_customers")({}, tenant_a)


# ─── Observabilité de la résolution vide ───

def test_an_empty_resolution_is_logged_without_being_treated_as_a_failure(
    caplog, tenant_a,
):
    """
    Personne à prévenir reste un résultat légitime, jamais un `_fail_log`.

    Mais un resolver muet par erreur laisse exactement la même absence de trace
    qu'un resolver muet à raison — la ligne de journal est le seul endroit où
    les deux deviennent distinguables.
    """
    import logging
    import uuid

    from django.utils import timezone

    make_templates_for_all_channels("notif.dispatch.responded.v1")

    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        result = NotificationService.emit(
            event_code="notif.dispatch.responded.v1",
            context={
                "assignment_id": str(uuid.uuid4()),
                "driver_name": "Ibrahima Sy",
                "response": "accepted",
                "responded_at": timezone.now(),
            },
            tenant=tenant_a,
        )

    assert result.skipped_no_recipient is True
    assert result.logs_failed == 0
    assert NotificationLog.objects.count() == 0
    assert "aucun destinataire résolu" in caplog.text
    assert "dispatch.dispatcher" in caplog.text
