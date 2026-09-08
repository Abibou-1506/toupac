"""
TOUPAC Notifications — Destinataires des événements d'exploitation.

Famille où le repli de rôles est le plus visible : la charte nomme responsable
flotte, mécanicien, IT, finance et responsable gare, que le modèle ne connaît
pas. Chaque resolver dit sur quoi son rôle de charte a été replié — sans quoi,
le jour où le lead demandera des rôles fins, personne ne saura où regarder.

`User.Role` n'est **pas** étendu ici : c'est un chantier produit, pas un effet
de bord d'un ticket de câblage.
"""
from ._helpers import (
    as_role_recipients,
    as_user_recipient,
    client_by_id,
    dedupe,
    staff_by_id,
    staff_with_roles,
)
from .base import register_resolver


@register_resolver("incident.dispatchers_and_admin")
def resolve_incident_dispatchers_and_admin(context, tenant):
    """INC-01 — régulateurs et administration de la compagnie."""
    from iam.models import User

    return as_role_recipients(
        staff_with_roles(tenant, User.Role.DISPATCHER, User.Role.ADMIN),
        User.Role.DISPATCHER,
    )


@register_resolver("incident.reporter_and_impacted")
def resolve_incident_reporter_and_impacted(context, tenant):
    """
    INC-02 — le déclarant, puis le client impacté s'il est identifié.

    Le déclarant est du personnel, le client impacté est global : deux
    populations, deux helpers. `impacted_user_id` est facultatif — un incident
    peut n'affecter aucun client nommément.
    """
    return dedupe(
        as_user_recipient(staff_by_id(context.get("reporter_user_id"), tenant)),
        as_user_recipient(client_by_id(context.get("impacted_user_id"))),
    )


@register_resolver("gps.dispatchers_and_fleet")
def resolve_gps_dispatchers_and_fleet(context, tenant):
    """
    GPS-01 — régulateurs et responsable flotte.

    « Responsable flotte » replié sur `ADMIN`.
    """
    from iam.models import User

    return as_role_recipients(
        staff_with_roles(tenant, User.Role.DISPATCHER, User.Role.ADMIN),
        User.Role.DISPATCHER,
    )


@register_resolver("gps.dispatchers_and_it")
def resolve_gps_dispatchers_and_it(context, tenant):
    """
    GPS-02 — régulateurs et IT.

    « IT » replié sur `ADMIN`, faute de rôle technique dans le modèle.

    Cette fonction résout aujourd'hui la même population que
    `gps.dispatchers_and_fleet`. Les fusionner serait une économie trompeuse :
    elles répondent à deux lignes de charte distinctes, et le jour où un rôle IT
    existera, c'est ici seulement qu'il faudra intervenir.
    """
    from iam.models import User

    return as_role_recipients(
        staff_with_roles(tenant, User.Role.DISPATCHER, User.Role.ADMIN),
        User.Role.DISPATCHER,
    )


@register_resolver("fleet.manager_and_mechanic")
def resolve_fleet_manager_and_mechanic(context, tenant):
    """
    FLT-01 — responsable flotte et mécanicien.

    Les deux repliés sur `ADMIN` : le modèle n'a ni l'un ni l'autre.
    """
    from iam.models import User

    return as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN)


@register_resolver("compliance.responsible_and_driver")
def resolve_compliance_responsible_and_driver(context, tenant):
    """
    CMP-01 — responsable flotte, puis le chauffeur concerné s'il y en a un.

    « Responsable flotte » replié sur `ADMIN`. `driver_user_id` est facultatif :
    un document réglementaire peut porter sur un véhicule sans chauffeur
    attitré, et le resolver rend alors la partie qu'il peut.
    """
    from iam.models import User

    driver = staff_by_id(context.get("driver_user_id"), tenant, User.Role.DRIVER)
    return dedupe(
        as_role_recipients(staff_with_roles(tenant, User.Role.ADMIN), User.Role.ADMIN),
        as_user_recipient(driver),
    )


@register_resolver("finance.finance_and_station")
def resolve_finance_finance_and_station(context, tenant):
    """
    FIN-01 — finance et responsable gare.

    « Finance » replié sur `ADMIN`, « responsable gare » sur `AGENT`.
    """
    from iam.models import User

    return as_role_recipients(
        staff_with_roles(tenant, User.Role.ADMIN, User.Role.AGENT), User.Role.ADMIN,
    )
