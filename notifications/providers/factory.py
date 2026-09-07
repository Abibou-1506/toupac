"""
TOUPAC Notifications — Fabrique du provider d'un canal.

Le mapping vit dans `settings.NOTIFICATION_PROVIDERS` plutôt que dans le code :
brancher une vraie passerelle SMS revient alors à changer un chemin pointé dans
le fichier de settings de l'environnement, sans toucher au service ni à la
tâche. C'est aussi ce qui permet à un test de substituer un provider par
`override_settings` sans patcher d'attribut privé.

Un canal absent du mapping retombe sur `ConsoleProvider`. Le choix est
délibéré : une notification imprimée vaut mieux qu'une exception au milieu
d'une émission — d'autant que ce provider ne divulgue rien hors développement.
"""
from django.conf import settings
from django.utils.module_loading import import_string

DEFAULT_FALLBACK = "notifications.providers.console.ConsoleProvider"


def get_provider(channel):
    """
    Instance du provider déclaré pour `channel`.

    Une instance neuve par appel, sans cache : les providers sont sans état et
    leur construction ne coûte rien, alors qu'une instance partagée entre les
    fils d'exécution d'un worker Celery serait un état commun à surveiller pour
    aucun gain.
    """
    providers_map = getattr(settings, "NOTIFICATION_PROVIDERS", {})
    dotted_path = providers_map.get(str(channel), DEFAULT_FALLBACK)
    return import_string(dotted_path)()
