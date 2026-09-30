"""
TOUPAC Notifications — Destinataires des événements d'authentification.

Seule famille de resolvers où le rôle du destinataire n'est pas connu à
l'avance : une connexion par code sert un client comme un chauffeur. D'où
`user_by_id`, qui ne présume de rien, là où tous les autres resolvers disent
explicitement quelle population ils cherchent.
"""
from ._helpers import as_role_recipients, as_user_recipient, dedupe, platform_admins, user_by_id
from .base import register_resolver


@register_resolver("auth.self")
def resolve_auth_self(context, tenant):
    """
    AUTH-01, AUTH-02 — l'intéressé, et lui seul.

    Aucun filtre de rôle : un salarié se connecte aussi. Aucun filtre de
    compagnie non plus, pour la même raison — un client n'en a pas, un salarié
    en a une, et la même clé sert les deux.

    La connexion par code passe par `emit()` avec `recipient_override` — le
    canal est imposé par la demande de l'utilisateur, et le destinataire
    désigné en clair pour ne pas se tromper de cible sur un compte multi-canaux.
    Ce resolver reste indispensable : il valide la présence du contexte
    `user_id` que `validate_context` exige, et sert aux autres émetteurs de la
    famille auth (AUTH-03).
    """
    return as_user_recipient(user_by_id(context.get("user_id")))


@register_resolver("auth.self_and_admins")
def resolve_auth_self_and_admins(context, tenant):
    """
    AUTH-03 — l'intéressé, puis les admins SI de la plateforme.

    « Admin SI » au sens de la charte est TOUPAC, pas l'administrateur de la
    compagnie : une activité suspecte sur un compte relève de l'exploitant de la
    plateforme. `tenant` n'est donc pas utilisé — les deux populations visées
    sont sans compagnie ou indifférentes à la sienne.
    """
    from iam.models import User

    return dedupe(
        as_user_recipient(user_by_id(context.get("user_id"))),
        as_role_recipients(platform_admins(), User.Role.SUPERADMIN),
    )
