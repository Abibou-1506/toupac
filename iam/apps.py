from django.apps import AppConfig


class IamConfig(AppConfig):
    name = "iam"

    def ready(self):
        # Importés pour leur enregistrement au chargement :
        # - schema : extension spectacular décrivant l'auth par clé API ;
        # - signals : provisionnement du compte de service à la création d'un tenant.
        from iam import (
            schema,  # noqa: F401
            signals,  # noqa: F401
        )
