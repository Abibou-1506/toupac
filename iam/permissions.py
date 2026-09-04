"""
TOUPAC IAM — Permissions et mixins liés aux scopes des clés API.

`HasApiScope` est branchée dans DEFAULT_PERMISSION_CLASSES : sans ça, tout
endpoint oublié serait ouvert à n'importe quelle clé. En étant globale, elle
refuse par défaut et n'autorise que ce qui déclare explicitement son scope.
Les vues qui redéfinissent `permission_classes` (auth, webhook, batch offline)
sortent du dispositif — elles ne sont pas destinées aux clés API.
"""
from rest_framework.permissions import BasePermission

from iam.models import ApiCredential
from iam.scopes import scope_for_action


class HasApiScope(BasePermission):
    """
    Vérifie que la clé API porte le scope exigé par la vue.

    Sans effet sur les requêtes authentifiées autrement (JWT, session) : les
    utilisateurs internes sont cadrés par leur rôle et leur tenant, pas par
    des scopes.
    """

    message = "Cette clé API n'a pas le scope requis pour cet endpoint."

    def has_permission(self, request, view):
        if not isinstance(request.auth, ApiCredential):
            return True

        required = self._required_scope(request, view)
        if required is None:
            # Endpoint non annoté : refus par défaut, pour qu'un oubli ferme
            # l'accès au lieu de l'ouvrir.
            self.message = "Cet endpoint n'est pas exposé aux clés API."
            return False

        return request.auth.has_scope(required)

    @staticmethod
    def _required_scope(request, view):
        explicit = getattr(view, "required_scope", None)
        if explicit:
            return explicit
        domain = getattr(view, "api_scope_domain", None)
        if domain:
            return scope_for_action(domain, getattr(view, "action", None))
        return None


class ApiScopedViewSetMixin:
    """
    Déclare le domaine de scope d'un ViewSet exposé à l'API publique.

    Le scope exact est dérivé de l'action : `list`/`retrieve` demandent
    `<domaine>:read`, tout le reste `<domaine>:write`. Un ViewSet en lecture
    seule côté partenaires n'a rien à déclarer de plus — il suffit de ne pas
    accorder le scope `:write` à sa clé.
    """

    api_scope_domain = None
