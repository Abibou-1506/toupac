from django.apps import AppConfig


class VoyageConfig(AppConfig):
    name = 'voyage'

    def ready(self):
        # Signaux : matérialisation TripStop à la création d'un Trip.
        from voyage import signals  # noqa: F401
