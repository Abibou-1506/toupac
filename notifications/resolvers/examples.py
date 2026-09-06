"""Exemples de resolvers testés.

Ces deux-là ne sont référencés par aucun événement du catalogue : ils existent
pour figer le contrat (signature, valeurs de `trigger_scope`, comportement
quand la cible est absente) que les resolvers métier du Ticket E devront
respecter. Leur préfixe `_example.` les distingue des clés de la matrice.
"""
from .base import ResolvedRecipient, register_resolver


@register_resolver("_example.customer_from_context")
def _resolve_customer(context, tenant):
    """Récupère un user par son user_id passé en contexte. Exemple de scope 'user'.

    Retourne une liste vide plutôt que de lever si la cible est introuvable :
    un destinataire disparu ne doit pas faire échouer l'émission des autres.
    """
    from iam.models import User

    user_id = context.get("user_id")
    if not user_id:
        return []
    user = User.objects.filter(id=user_id, tenant=tenant).first()
    if user is None:
        return []
    return [ResolvedRecipient(user=user, trigger_scope="user")]


@register_resolver("_example.dispatchers_of_tenant")
def _resolve_dispatchers(context, tenant):
    """Tous les dispatchers actifs du tenant. Exemple de scope 'role' (broadcast)."""
    from iam.models import User

    users = User.objects.filter(tenant=tenant, role=User.Role.DISPATCHER, is_active=True)
    return [
        ResolvedRecipient(user=u, trigger_scope="role", trigger_role=User.Role.DISPATCHER)
        for u in users
    ]
