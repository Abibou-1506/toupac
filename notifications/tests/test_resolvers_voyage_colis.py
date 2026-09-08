"""
TOUPAC Notifications — Resolvers de voyage, de dispatch, de contrôle et de colis.

Deux points s'y jouent que les autres familles ne posent pas : la composition de
plusieurs sources — voyageurs, chauffeur, personnel — qui impose la
déduplication, et le fait qu'un billet annulé n'a plus de titulaire à prévenir.
"""
import uuid

import pytest
from django.utils import timezone

from iam.models import User
from iam.tests.customer_factories import make_reservation
from notifications.resolvers.base import get_resolver
from voyage.models import Reservation

pytestmark = pytest.mark.django_db


def resolve(key, context=None, tenant=None):
    return get_resolver(key)(context or {}, tenant)


def pks(resolved):
    return {entry.user.pk for entry in resolved}


# ─── Les voyageurs d'un trajet ───

def test_trip_customer_and_driver_gathers_both(trip_with_two_passengers, tenant_a):
    decor = trip_with_two_passengers

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert found == {c.pk for c in decor.customers} | {decor.driver_user.pk}


def test_a_cancelled_reservation_no_longer_has_a_holder_to_warn(
    trip_with_two_passengers, tenant_a,
):
    """
    Prévenir d'un retard le titulaire d'un billet annulé est un envoi facturé
    pour rien, et un message sans aucun sens pour qui le reçoit.
    """
    decor = trip_with_two_passengers
    cancelled = decor.reservations[0]
    cancelled.status = Reservation.Status.CANCELLED
    cancelled.save(update_fields=["status"])

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert cancelled.passenger.customer_user.pk not in found
    assert decor.customers[1].pk in found


def test_a_refused_reservation_is_excluded_too(trip_with_two_passengers, tenant_a):
    decor = trip_with_two_passengers
    refused = decor.reservations[0]
    refused.status = Reservation.Status.REFUSED
    refused.save(update_fields=["status"])

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert refused.passenger.customer_user.pk not in found


def test_a_boarded_reservation_still_has_a_holder(trip_with_two_passengers, tenant_a):
    """Seules l'annulation et le refus retirent le titulaire, pas l'embarquement."""
    decor = trip_with_two_passengers
    boarded = decor.reservations[0]
    boarded.status = Reservation.Status.BOARDED
    boarded.save(update_fields=["status"])

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert boarded.passenger.customer_user.pk in found


def test_a_guest_passenger_is_not_resolved(tenant_a, trip_with_two_passengers):
    """Un passager sans compte ne peut pas être joint — il n'est pas rendu."""
    decor = trip_with_two_passengers
    make_reservation(tenant_a, customer_user=None, trip=decor.trip)

    found = resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    )

    assert len(found) == 3  # deux voyageurs + le chauffeur, pas l'invité


def test_an_erased_passenger_record_is_not_resolved(
    trip_with_two_passengers, tenant_a,
):
    """Une fiche effacée au titre du RGPD ne doit plus rien déclencher."""
    decor = trip_with_two_passengers
    passenger = decor.reservations[0].passenger
    passenger.deleted_at = timezone.now()
    passenger.save(update_fields=["deleted_at"])

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert decor.customers[0].pk not in found


def test_a_trip_without_a_driver_resolves_only_its_travellers(
    trip_with_two_passengers, tenant_a,
):
    decor = trip_with_two_passengers
    decor.trip.driver = None
    decor.trip.save(update_fields=["driver"])

    found = pks(resolve(
        "trip.customer_and_driver", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert found == {c.pk for c in decor.customers}


def test_a_missing_trip_resolves_to_nobody(tenant_a):
    assert resolve("trip.customer_and_driver", {"trip_id": uuid.uuid4()}, tenant_a) == []
    assert resolve("trip.customer_and_driver", {}, tenant_a) == []


def test_trip_all_stakeholders_adds_the_agents(
    trip_with_two_passengers, user_agent_a, tenant_a,
):
    decor = trip_with_two_passengers

    found = pks(resolve(
        "trip.all_stakeholders", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert found == (
        {c.pk for c in decor.customers} | {decor.driver_user.pk, user_agent_a.pk}
    )


def test_a_person_present_in_two_sources_is_resolved_once(
    trip_with_two_passengers, tenant_a,
):
    """
    Le chauffeur voyage aussi comme client de sa propre compagnie.

    La contrainte d'unicité de `Notification` absorberait le doublon côté centre
    d'alertes, mais les envois, eux, partiraient deux fois — et sur les canaux
    facturés, cela se paie deux fois.
    """
    decor = trip_with_two_passengers
    make_reservation(tenant_a, customer_user=decor.driver_user, trip=decor.trip)

    resolved = resolve(
        "trip.all_stakeholders", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    )

    assert len(resolved) == len(pks(resolved))
    driver_entries = [e for e in resolved if e.user.pk == decor.driver_user.pk]
    assert len(driver_entries) == 1
    # La première source rencontrée l'emporte : il est voyageur avant d'être
    # chauffeur, et c'est le scope le plus spécifique.
    assert driver_entries[0].trigger_scope == "user"


def test_trip_customer_and_station_adds_the_agents(
    trip_with_two_passengers, user_agent_a, tenant_a,
):
    decor = trip_with_two_passengers

    found = pks(resolve(
        "trip.customer_and_station", {"trip_id": decor.trip.pk}, tenant=tenant_a,
    ))

    assert found == {c.pk for c in decor.customers} | {user_agent_a.pk}
    assert decor.driver_user.pk not in found


# ─── Dispatch ───

def test_dispatch_driver_reaches_the_named_driver(user_driver_a, tenant_a):
    found = pks(resolve(
        "dispatch.driver", {"driver_user_id": user_driver_a.pk}, tenant=tenant_a,
    ))

    assert found == {user_driver_a.pk}


def test_dispatch_driver_refuses_an_identifier_from_another_company(
    user_driver_a, tenant_b,
):
    """Un identifiant venu d'ailleurs ne doit pas faire sortir l'affectation."""
    assert resolve(
        "dispatch.driver", {"driver_user_id": user_driver_a.pk}, tenant=tenant_b,
    ) == []


def test_dispatch_driver_refuses_an_account_that_is_not_a_driver(
    user_dispatcher_a, tenant_a,
):
    assert resolve(
        "dispatch.driver", {"driver_user_id": user_dispatcher_a.pk}, tenant=tenant_a,
    ) == []


def test_dispatch_dispatcher_broadcasts_to_the_company(user_dispatcher_a, tenant_a):
    resolved = resolve("dispatch.dispatcher", {}, tenant=tenant_a)

    assert pks(resolved) == {user_dispatcher_a.pk}
    assert resolved[0].trigger_scope == "role"
    assert resolved[0].trigger_role == User.Role.DISPATCHER


def test_dispatch_dispatcher_never_reaches_a_client(
    user_dispatcher_a, client_fatou, tenant_a,
):
    """
    La charte note explicitement pour DSP-03 « ne pas envoyer au client ».

    C'est le genre de note qu'un resolver trop généreux violerait sans bruit.
    """
    assert client_fatou.pk not in pks(resolve("dispatch.dispatcher", {}, tenant=tenant_a))


def test_dispatch_dispatcher_is_isolated_by_company(
    user_dispatcher_a, user_dispatcher_b, tenant_a,
):
    assert pks(resolve("dispatch.dispatcher", {}, tenant=tenant_a)) == {
        user_dispatcher_a.pk,
    }


def test_a_company_without_dispatchers_resolves_to_nobody(tenant_a):
    assert resolve("dispatch.dispatcher", {}, tenant=tenant_a) == []


def test_a_broadcast_without_a_company_resolves_to_nobody(user_dispatcher_a):
    """Diffuser à « tous les dispatchers » sans compagnie les toucherait toutes."""
    assert resolve("dispatch.dispatcher", {}, tenant=None) == []


def test_a_deactivated_member_is_never_broadcast_to(user_dispatcher_a, tenant_a):
    user_dispatcher_a.is_active = False
    user_dispatcher_a.save(update_fields=["is_active"])

    assert resolve("dispatch.dispatcher", {}, tenant=tenant_a) == []


# ─── Contrôle ───

def test_control_gathers_the_controller_and_the_supervisors(
    user_controller_a, user_dispatcher_a, user_admin_a, tenant_a,
):
    found = pks(resolve(
        "control.controller_and_supervisor",
        {"controller_user_id": user_controller_a.pk}, tenant=tenant_a,
    ))

    assert found == {user_controller_a.pk, user_dispatcher_a.pk, user_admin_a.pk}


def test_control_still_warns_the_supervisors_without_the_controller(
    user_dispatcher_a, tenant_a,
):
    found = pks(resolve(
        "control.controller_and_supervisor", {}, tenant=tenant_a,
    ))

    assert found == {user_dispatcher_a.pk}


# ─── Colis ───

def test_parcel_sender_and_recipient_gathers_both(
    parcel_order, client_fatou, client_aicha,
):
    found = pks(resolve(
        "parcel.sender_and_recipient", {"order_id": parcel_order.pk},
    ))

    assert found == {client_fatou.pk, client_aicha.pk}


def test_parcel_sender_keeps_only_the_sender(parcel_order, client_fatou, client_aicha):
    found = pks(resolve("parcel.sender", {"order_id": parcel_order.pk}))

    assert found == {client_fatou.pk}
    assert client_aicha.pk not in found


def test_parcel_recipient_keeps_only_the_recipient(
    parcel_order, client_fatou, client_aicha,
):
    """
    COL-05 est le code de retrait : il autorise à repartir avec le colis.

    L'envoyer à l'expéditeur n'aurait aucun sens et lui donnerait le moyen de
    retirer un colis qu'il a lui-même envoyé.
    """
    found = pks(resolve("parcel.recipient", {"order_id": parcel_order.pk}))

    assert found == {client_aicha.pk}
    assert client_fatou.pk not in found


def test_a_parcel_without_a_registered_recipient_resolves_to_nobody(
    tenant_a, client_fatou,
):
    """
    Cas majoritaire aujourd'hui : le destinataire n'a pas de compte TOUPAC.

    Le champ existe désormais ; le remplir viendra avec les endpoints d'écriture
    du client.
    """
    from iam.tests.customer_factories import make_order

    order = make_order(tenant_a, customer=client_fatou)

    assert resolve("parcel.recipient", {"order_id": order.pk}) == []
    assert pks(resolve("parcel.sender_and_recipient", {"order_id": order.pk})) == {
        client_fatou.pk,
    }


def test_sending_a_parcel_to_oneself_resolves_once(tenant_a, client_fatou):
    from iam.tests.customer_factories import make_order

    order = make_order(tenant_a, customer=client_fatou)
    order.recipient_user = client_fatou
    order.save(update_fields=["recipient_user"])

    resolved = resolve("parcel.sender_and_recipient", {"order_id": order.pk})

    assert len(resolved) == 1


def test_a_missing_parcel_resolves_to_nobody():
    for key in ("parcel.sender", "parcel.recipient", "parcel.sender_and_recipient"):
        assert resolve(key, {"order_id": uuid.uuid4()}) == []
        assert resolve(key, {}) == []
