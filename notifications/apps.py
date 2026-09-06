from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        # Peuple les registres : catalogue des 37 événements et resolvers.
        # Aucun signal, aucun autre effet de bord — les déclarations valident
        # leur propre cohérence à l'import, donc une erreur de catalogue casse
        # au démarrage plutôt qu'au premier envoi.
        from . import catalog  # noqa: F401
        from .resolvers import examples  # noqa: F401
