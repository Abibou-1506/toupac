from django.apps import AppConfig


class IamConfig(AppConfig):
    name = "iam"

    def ready(self):
        # Enregistre l'extension spectacular décrivant l'auth par clé API.
        # L'import suffit : la classe s'inscrit à sa définition.
        from iam import schema  # noqa: F401
