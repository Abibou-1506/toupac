"""
TOUPAC Notifications — Destinataires des commandes, paiements et billets.

Tous ces resolvers visent d'abord un **client**, qui est global et sans
compagnie (USR-1). Le filtrer par `tenant` ne rendrait jamais rien : c'est le
lien métier — la commande, le paiement, la réservation — qui porte l'isolation,
et il la porte strictement puisqu'il appartient déjà à sa compagnie.
"""
from ._helpers import as_role_recipients, as_user_recipient, dedupe, staff_with_roles
from .base import register_resolver

#: Valeurs de `order_type` (variable de rendu du catalogue) et modèle visé.
#: Une commande TOUPAC est soit un billet de voyage, soit un envoi de colis :
#: deux tables distinctes, un seul événement de charte.
_ORDER_TYPES = {"reservation", "parcel"}


def _order_customer(context):
    """Le client d'une commande, quel que soit le type d'objet derrière."""
    order_type = context.get("order_type")
    order_id = context.get("order_id")
    if order_type not in _ORDER_TYPES or not order_id:
        # Un type inconnu ne se devine pas : rendre `[]` laisse la trace
        # « aucun destinataire résolu » dans le journal, ce qui est exact.
        return None

    if order_type == "parcel":
        from colis.models import Order

        order = (
            Order.objects.filter(pk=order_id, deleted_at__isnull=True)
            .select_related("customer").first()
        )
        return order.customer if order else None

    from voyage.models import Reservation

    reservation = (
        Reservation.objects.filter(pk=order_id)
        .select_related("passenger__customer_user").first()
    )
    return reservation.passenger.customer_user if reservation else None


@register_resolver("order.customer")
def resolve_order_customer(context, tenant):
    """CMD-01, CMD-02 — le client de la commande."""
    return as_user_recipient(_order_customer(context))


@register_resolver("order.customer_and_agent")
def resolve_order_customer_and_agent(context, tenant):
    """
    CMD-03 — le client, puis les agents de guichet.

    « Agent service client » de la charte est replié sur `AGENT` : le modèle ne
    distingue pas le guichet du service client.
    """
    from iam.models import User

    return dedupe(
        as_user_recipient(_order_customer(context)),
        as_role_recipients(staff_with_roles(tenant, User.Role.AGENT), User.Role.AGENT),
    )


def _payment_customer(context):
    """
    Le client d'un paiement — trois chemins possibles, pas deux.

    `Payment` ne porte aucun lien direct vers un payeur : il se relie à une
    commande de colis, à une réservation, ou à une facture. Les trois sont
    nullables et indépendants. La facture, elle, désigne son client par le
    couple polymorphe (`customer_id`, `customer_type`) : lire l'identifiant sans
    vérifier le type ouvrirait la facture d'un client externe dont l'identifiant
    coïnciderait avec celui d'un compte TOUPAC.
    """
    from billing.models import CUSTOMER_TYPE_CLIENT_USER, Payment
    from iam.models import User

    payment_id = context.get("payment_id")
    if not payment_id:
        return None

    payment = (
        Payment.objects.filter(pk=payment_id)
        .select_related(
            "order__customer", "reservation__passenger__customer_user", "invoice",
        )
        .first()
    )
    if payment is None:
        return None

    if payment.order_id and payment.order.customer_id:
        return payment.order.customer
    if payment.reservation_id and payment.reservation.passenger.customer_user_id:
        return payment.reservation.passenger.customer_user
    if payment.invoice_id and payment.invoice.customer_type == CUSTOMER_TYPE_CLIENT_USER:
        return User.objects.filter(
            pk=payment.invoice.customer_id, role=User.Role.CLIENT, is_active=True,
        ).first()
    return None


@register_resolver("payment.customer")
def resolve_payment_customer(context, tenant):
    """PAY-01, PAY-02 — le client qui a payé."""
    return as_user_recipient(_payment_customer(context))


@register_resolver("payment.customer_and_finance")
def resolve_payment_customer_and_finance(context, tenant):
    """
    PAY-03 — le client, puis la finance de la compagnie.

    « Finance » de la charte est replié sur `ADMIN` : le modèle n'a pas de rôle
    comptable, et l'admin de compagnie est le seul à voir les remboursements.
    """
    from iam.models import User

    return dedupe(
        as_user_recipient(_payment_customer(context)),
        as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN),
    )


@register_resolver("ticket.customer")
def resolve_ticket_customer(context, tenant):
    """
    TKT-01 — le voyageur titulaire du billet.

    `Passenger.customer_user` est nullable : un billet vendu au guichet à
    quelqu'un sans compte n'a pas de destinataire joignable. Rendre `[]` est
    alors la bonne réponse — fabriquer un destinataire serait pire.
    """
    from voyage.models import Reservation

    reservation_id = context.get("reservation_id")
    if not reservation_id:
        return []

    reservation = (
        Reservation.objects.filter(pk=reservation_id)
        .select_related("passenger__customer_user").first()
    )
    if reservation is None:
        return []
    return as_user_recipient(reservation.passenger.customer_user)
