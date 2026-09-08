"""
TOUPAC Notifications — Destinataires des événements transverses.

Approbations, stock, réclamations, campagnes, pilotage, plateforme. Deux points
y méritent d'être lus avant d'y toucher : le périmètre des campagnes marketing,
et le fait que `si.admins_and_support` vise TOUPAC, pas la compagnie.
"""
from ._helpers import (
    as_role_recipients,
    as_user_recipient,
    client_by_id,
    dedupe,
    platform_admins,
    staff_by_id,
    staff_with_roles,
)
from .base import ResolvedRecipient, register_resolver


@register_resolver("approval.approver")
def resolve_approval_approver(context, tenant):
    """
    APR-01 — l'approbateur désigné, sinon l'administration.

    « Approbateur » n'existe pas dans le modèle : quand le contexte n'en nomme
    pas, le repli est `ADMIN`. Une demande d'approbation qui ne toucherait
    personne resterait en attente indéfiniment, ce qui est pire qu'un
    destinataire approximatif.
    """
    from iam.models import User

    approver = staff_by_id(context.get("approver_user_id"), tenant)
    if approver is not None:
        return as_user_recipient(approver)
    return as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN)


@register_resolver("stock.warehouse_and_purchase")
def resolve_stock_warehouse_and_purchase(context, tenant):
    """
    STK-01 — magasinier et achats, tous deux repliés sur `ADMIN`.
    """
    from iam.models import User

    return as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN)


@register_resolver("crm.customer_and_agent")
def resolve_crm_customer_and_agent(context, tenant):
    """
    CRM-01 — le client réclamant, puis les agents.

    « Agent service client » replié sur `AGENT` : le modèle ne distingue pas le
    guichet du service client.
    """
    from iam.models import User

    return dedupe(
        as_user_recipient(client_by_id(context.get("customer_user_id"))),
        as_role_recipients(staff_with_roles(tenant, User.Role.AGENT), User.Role.AGENT),
    )


@register_resolver("marketing.consented_customers")
def resolve_marketing_consented_customers(context, tenant):
    """
    MKT-01 — les clients de **cette** compagnie.

    Deux points que le nom de la clé ne dit pas, et qui comptent tous les deux.

    **Périmètre.** Les clients ayant au moins une réservation ou une commande
    chez ce transporteur — jamais la base clients globale de la plateforme. Une
    compagnie n'a aucun titre à toucher les clients d'une autre, et un client
    global (USR-1) appartient à tout le monde et à personne.

    **Consentement.** Ce resolver ne lit pas `notification_preferences`, malgré
    son nom. L'opt-out de la catégorie `marketing` est appliqué en aval par
    `_passes_preferences()` : le dupliquer ici créerait deux endroits à tenir
    pour une même règle, qui divergeraient au premier changement. Le resolver
    rend donc des clients qui seront ensuite écartés, et c'est correct.
    """
    from django.db.models import Q

    from iam.models import User

    if tenant is None:
        return []

    customers = (
        User.objects.filter(role=User.Role.CLIENT, is_active=True)
        .filter(
            Q(
                passenger_records__tenant=tenant,
                passenger_records__deleted_at__isnull=True,
            )
            | Q(orders__tenant=tenant, orders__deleted_at__isnull=True)
        )
        # Les deux branches peuvent désigner le même client — quelqu'un qui a
        # voyagé et expédié — et la jointure le rendrait alors deux fois.
        .distinct()
        .order_by("pk")
    )
    return [
        ResolvedRecipient(user=user, trigger_scope="tenant")
        for user in customers
    ]


@register_resolver("bi.direction_and_finance")
def resolve_bi_direction_and_finance(context, tenant):
    """
    BI-01 — direction et finance, toutes deux repliées sur `ADMIN`.
    """
    from iam.models import User

    return as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN)


@register_resolver("si.admins_and_support")
def resolve_si_admins_and_support(context, tenant):
    """
    SI-01 — les admins SI de TOUPAC, pas ceux de la compagnie.

    Un incident de plateforme relève de son exploitant. `tenant` n'est pas
    utilisé : les `SUPERADMIN` sont sans compagnie par contrainte de base, et
    prévenir l'administrateur d'un client d'une panne interne lui donnerait une
    information qu'il ne peut pas exploiter.
    """
    from iam.models import User

    return as_role_recipients(platform_admins(), User.Role.SUPERADMIN)
