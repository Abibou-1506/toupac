from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        # Peuple les registres : catalogue des 37 événements et resolvers.
        # Aucun signal, aucun autre effet de bord — les déclarations valident
        # leur propre cohérence à l'import, donc une erreur de catalogue casse
        # au démarrage plutôt qu'au premier envoi.
        # Un module de resolvers non importé ici n'enregistre rien, et le seul
        # symptôme serait un `resolver_missing:` en production — d'où
        # l'invariant croisé de `test_resolvers.py`, qui rend l'oubli rouge.
        from . import catalog  # noqa: F401
        from .resolvers import (  # noqa: F401
            auth,
            colis,
            commerce,
            examples,
            operations,
            transverse,
            voyage,
        )
