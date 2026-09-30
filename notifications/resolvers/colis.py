"""
TOUPAC Notifications — Destinataires des événements de colis.

Deux personnes distinctes gravitent autour d'un envoi : celui qui l'expédie et
celui qui l'attend. Le second n'était modélisé nulle part avant ce ticket
(`Order.recipient_user`), ce qui rendait COL-04 et COL-05 — le code de retrait —
sans destinataire à résoudre.

`recipient_user` reste nullable et souvent vide : un destinataire n'a pas
toujours de compte TOUPAC. Un resolver qui rend `[]` dit alors la vérité, et
`Order.recipient_name` / `recipient_phone` gardent trace de qui l'on cherchait.
"""
from ._helpers import as_user_recipient, dedupe
from .base import register_resolver


def _order(order_id, tenant):
    """
    La commande de colis appartenant à `tenant`, avec ses deux comptes chargés.

    Le filtre `tenant` est ce qui distingue ce lookup de « n'importe quelle
    commande dont on connaît l'identifiant ». `Order.objects` ne filtre pas de
    lui-même (doctrine « filtrage explicite assumé », cf. DECISIONS.md, section
    Multi-tenant) : sans cette ligne, un `order_id` d'une autre compagnie
    remonterait le destinataire de sa commande à un émetteur qui n'y a pas droit.

    Rendre `None` sur `tenant is None` est cohérent avec le contrat des
    resolvers : un event colis appartient toujours à un transporteur, l'appeler
    sans tenant est un défaut d'émission plutôt qu'un cas légitime, et rendre
    `[]` en aval laisse la trace `skipped_no_recipient` qui va bien plutôt qu'un
    envoi qui aurait franchi la frontière.
    """
    from colis.models import Order

    if not order_id or tenant is None:
        return None
    return (
        Order.objects.filter(pk=order_id, tenant=tenant, deleted_at__isnull=True)
        .select_related("customer", "recipient_user")
        .first()
    )


@register_resolver("parcel.sender_and_recipient")
def resolve_parcel_sender_and_recipient(context, tenant):
    """
    COL-01, COL-06 — l'expéditeur puis le destinataire.

    L'ordre porte l'intention : l'expéditeur d'abord, parce qu'il est le client
    de la compagnie. Les deux peuvent être la même personne — quelqu'un qui
    s'expédie un colis à lui-même — d'où la déduplication.
    """
    order = _order(context.get("order_id"), tenant)
    if order is None:
        return []
    return dedupe(
        as_user_recipient(order.customer),
        as_user_recipient(order.recipient_user),
    )


@register_resolver("parcel.sender")
def resolve_parcel_sender(context, tenant):
    """COL-02, COL-03 — l'expéditeur, commanditaire de l'envoi."""
    order = _order(context.get("order_id"), tenant)
    return as_user_recipient(order.customer) if order else []


@register_resolver("parcel.recipient")
def resolve_parcel_recipient(context, tenant):
    """
    COL-04, COL-05 — celui qui attend le colis.

    COL-05 est le code de retrait : c'est lui qui autorise à repartir avec le
    colis, et il n'a aucun sens envoyé à l'expéditeur.
    """
    order = _order(context.get("order_id"), tenant)
    return as_user_recipient(order.recipient_user) if order else []
