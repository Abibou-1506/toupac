"""
TOUPAC Notifications — Destinataires des événements de voyage.

Trois resolvers partagent « les clients d'un voyage » et passent donc par le
même helper. Il filtre sur les réservations **non annulées** : prévenir d'un
retard le titulaire d'un billet annulé est un envoi facturé pour rien, et un
message qui n'a aucun sens pour qui le reçoit.
"""
from ._helpers import (
    as_role_recipients,
    as_user_recipient,
    dedupe,
    staff_by_id,
    staff_with_roles,
)
from .base import ResolvedRecipient, register_resolver

#: Statuts qui ne valent plus engagement de voyage. Exprimé en exclusion plutôt
#: qu'en liste blanche, et repris tel quel de la contrainte d'unicité du siège
#: sur `Reservation` : une place occupée et un titulaire à prévenir sont la même
#: question. Une liste blanche aurait dû être tenue à jour à deux endroits.
#:
#: Il n'existe pas de statut « confirmée » — les statuts sont `booked`,
#: `checked_in`, `boarded`, `no_show`, `refused`, `cancelled`.
_VOID_RESERVATION_STATUSES = ("cancelled", "refused")


def _trip_customers(trip_id):
    """Comptes clients titulaires d'une réservation vivante sur ce voyage."""
    from voyage.models import Reservation

    if not trip_id:
        return []
    reservations = (
        Reservation.objects.filter(
            trip_id=trip_id,
            passenger__customer_user__isnull=False,
            passenger__deleted_at__isnull=True,
        )
        .exclude(status__in=_VOID_RESERVATION_STATUSES)
        .select_related("passenger__customer_user")
        .order_by("pk")
    )
    return [
        ResolvedRecipient(user=r.passenger.customer_user, trigger_scope="user")
        for r in reservations
    ]


def _trip_driver(trip_id):
    """
    Le chauffeur affecté au voyage, ramené à son compte utilisateur.

    `Trip.driver` pointe sur `fleet.Driver`, pas sur `iam.User` : le profil
    chauffeur porte permis et score, le compte porte l'identité et les canaux.
    """
    from voyage.models import Trip

    if not trip_id:
        return []
    trip = (
        Trip.objects.filter(pk=trip_id)
        .select_related("driver__user").first()
    )
    if trip is None or trip.driver_id is None or not trip.driver.user.is_active:
        return []
    return [
        ResolvedRecipient(
            user=trip.driver.user, trigger_scope="user", trigger_role="driver",
        )
    ]


@register_resolver("trip.customer_and_driver")
def resolve_trip_customer_and_driver(context, tenant):
    """TRJ-01, TRJ-02 — les voyageurs, puis le chauffeur."""
    trip_id = context.get("trip_id")
    return dedupe(_trip_customers(trip_id), _trip_driver(trip_id))


@register_resolver("trip.all_stakeholders")
def resolve_trip_all_stakeholders(context, tenant):
    """
    TRJ-04 — voyageurs, chauffeur, puis les agents de la compagnie.

    Le resolver le plus susceptible de rendre deux fois la même personne : un
    chauffeur peut être client de sa propre compagnie. La déduplication garde la
    première occurrence, donc le rôle de voyageur, qui est le plus spécifique.
    """
    from iam.models import User

    trip_id = context.get("trip_id")
    return dedupe(
        _trip_customers(trip_id),
        _trip_driver(trip_id),
        as_role_recipients(staff_with_roles(tenant, User.Role.AGENT), User.Role.AGENT),
    )


@register_resolver("trip.customer_and_station")
def resolve_trip_customer_and_station(context, tenant):
    """
    TRJ-03 — les voyageurs, puis la gare de départ.

    « Responsable gare » de la charte est replié sur `AGENT` : le modèle ne
    distingue pas le guichetier de son responsable.
    """
    from iam.models import User

    return dedupe(
        _trip_customers(context.get("trip_id")),
        as_role_recipients(staff_with_roles(tenant, User.Role.AGENT), User.Role.AGENT),
    )


@register_resolver("dispatch.driver")
def resolve_dispatch_driver(context, tenant):
    """
    DSP-01 — le chauffeur affecté, et lui seul.

    Le contexte porte directement son compte : une affectation se notifie à la
    personne, pas au profil chauffeur. Le contrôle de compagnie empêche qu'un
    identifiant venu d'ailleurs fasse sortir l'affectation de la sienne.
    """
    from iam.models import User

    driver = staff_by_id(context.get("driver_user_id"), tenant, User.Role.DRIVER)
    if driver is None:
        return []
    return [ResolvedRecipient(user=driver, trigger_scope="user", trigger_role=User.Role.DRIVER)]


@register_resolver("dispatch.dispatcher")
def resolve_dispatch_dispatcher(context, tenant):
    """
    DSP-02, DSP-03 — les régulateurs de la compagnie.

    La charte note explicitement pour DSP-03 « ne pas envoyer au client » : ce
    resolver ne rend que du personnel, et un test l'assure.
    """
    from iam.models import User

    return as_role_recipients(
        staff_with_roles(tenant, User.Role.DISPATCHER), User.Role.DISPATCHER,
    )


@register_resolver("control.controller_and_supervisor")
def resolve_control_controller_and_supervisor(context, tenant):
    """
    CTL-01 — le contrôleur concerné, puis sa hiérarchie.

    « Superviseur contrôle » de la charte est replié sur `DISPATCHER` + `ADMIN` :
    le modèle n'a pas de rôle de supervision du contrôle, et ce sont ces deux-là
    qui arbitrent un billet refusé.
    """
    from iam.models import User

    controller = staff_by_id(
        context.get("controller_user_id"), tenant, User.Role.CONTROLLER,
    )
    supervisors = staff_with_roles(tenant, User.Role.DISPATCHER, User.Role.ADMIN)
    return dedupe(
        as_user_recipient(controller),
        as_role_recipients(supervisors, User.Role.DISPATCHER),
    )
