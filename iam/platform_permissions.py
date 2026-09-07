"""
TOUPAC IAM — Permissions des clés plateforme.

`HasPlatformScope` est branchée dans DEFAULT_PERMISSION_CLASSES, en miroir de
`HasApiScope` : sans ça, tout endpoint oublié serait ouvert à n'importe quelle
clé plateforme. Elle refuse par défaut et n'autorise que ce qui déclare son
scope, explicitement ou via `api_scope_domain`.

Les deux permissions sont sans effet sur les requêtes authentifiées autrement
(JWT, session, clé tenant) : chaque backend a son propre dispositif.
"""
from rest_framework import exceptions
from rest_framework.permissions import BasePermission

from iam.models import PlatformCredential
from iam.platform_authentication import TENANT_HEADER
from iam.platform_scopes import GLOBAL_SCOPE, platform_scope_for_domain
from iam.scopes import READ_ACTIONS


def _credential(request):
    """La `PlatformCredential` de la requête, ou None si elle vient d'ailleurs."""
    auth = getattr(request, "auth", None)
    return auth if isinstance(auth, PlatformCredential) else None


class HasPlatformScope(BasePermission):
    """
    Vérifie que la clé plateforme porte le scope exigé par la vue.

    Depuis USR-4, l'écriture métier est ouverte : le partenaire peut réserver,
    expédier ou payer. Elle est encadrée par deux conditions cumulatives — le
    scope d'écriture du domaine, et un client désigné. Écrire sans savoir pour
    qui attribuerait la réservation au porteur technique, c'est-à-dire à
    personne, et rendrait l'enregistrement irrattachable à son titulaire.
    """

    message = "Cette clé plateforme n'a pas le scope requis pour cet endpoint."

    def has_permission(self, request, view):
        from iam.models import User

        credential = _credential(request)
        if credential is None:
            return True

        required = self._required_scope(view)
        if required is None:
            # Endpoint non annoté : refus par défaut, pour qu'un oubli ferme
            # l'accès au lieu de l'ouvrir.
            self.message = "Cet endpoint n'est pas exposé aux clés plateforme."
            return False

        if not credential.has_platform_scope(required):
            self.message = (
                f"Cette clé plateforme n'a pas le scope {required}, requis pour "
                "cet endpoint."
            )
            return False

        if self._is_write(view) and getattr(request.user, "role", None) != User.Role.CLIENT:
            self.message = (
                "Une écriture se fait toujours au nom d'un client : indiquez-le avec "
                "l'en-tête X-Acting-User-Email (ou X-Acting-User-Phone)."
            )
            return False

        return True

    @staticmethod
    def _is_write(view):
        domain = getattr(view, "api_scope_domain", None)
        if not domain:
            return False
        return getattr(view, "action", None) not in READ_ACTIONS

    @classmethod
    def _required_scope(cls, view):
        explicit = getattr(view, "platform_required_scope", None)
        if explicit:
            return explicit

        # Les ViewSets métier déclarent déjà leur domaine pour les clés tenant.
        # On en dérive le scope plateforme plutôt que de les réannoter un par un,
        # ce qui laisserait les deux listes diverger au premier ajout.
        domain = getattr(view, "api_scope_domain", None)
        if not domain:
            return None
        if cls._is_write(view):
            # Un domaine sans scope d'écriture déclaré (tracking, par exemple)
            # produit ici un scope qu'aucune clé ne peut porter : le refus est
            # alors automatique, sans liste à tenir à jour.
            return platform_scope_for_domain(domain, write=True)
        return platform_scope_for_domain(domain)


class IsPlatformTenantContextValid(BasePermission):
    """
    Fait respecter le contrat du header `X-Tenant-ID`.

    - Endpoint global (`platform:global:read`) : le header doit être absent.
      Le présenter signale un appelant qui croit filtrer par tenant alors que la
      réponse est globale — mieux vaut le lui dire que lui rendre une réponse
      qu'il interprétera de travers.
    - Endpoint tenant : le header est obligatoire, sans quoi la requête serait
      servie sans contexte et les querysets rendraient du vide silencieux.

    Lève `ValidationError` (400) plutôt que de renvoyer False (403) : ce n'est
    pas un défaut d'autorisation mais une requête mal formée, et un 403 enverrait
    l'intégrateur chercher un scope manquant qui n'a rien à voir.
    """

    def has_permission(self, request, view):
        credential = _credential(request)
        if credential is None:
            return True

        # Le header brut, pas request.tenant : sur un endpoint global on doit
        # détecter la présence du header même si sa résolution a échoué.
        header_present = bool(request.META.get(TENANT_HEADER, "").strip())
        is_global = getattr(view, "platform_required_scope", None) == GLOBAL_SCOPE

        if is_global and header_present:
            raise exceptions.ValidationError({
                "detail": "Cet endpoint est global : ne transmettez pas le header X-Tenant-ID.",
            })

        if not is_global and not header_present:
            raise exceptions.ValidationError({
                "detail": "Header X-Tenant-ID manquant : indiquez le slug du tenant visé "
                          "(ex. « sahel-express »). La liste des tenants abonnés est "
                          "disponible sur GET /api/v1/platform/tenants/.",
            })

        return True
