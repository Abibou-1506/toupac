"""TOUPAC Notifications — Interface abstraite des providers d'envoi."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings

#: Ce que l'on écrit à la place du message hors développement.
REDACTED = "[contenu masqué hors développement]"


def loggable_body(message, subject=""):
    """
    Ce qu'un provider qui journalise en clair a le droit d'écrire.

    Règle unique, partagée par les trois providers qui n'envoient rien et se
    contentent d'imprimer : console, mock SMS, mock WhatsApp. Hors
    développement, le corps est retenu — un code de connexion, un QR de billet
    ou un montant se retrouveraient sinon en clair dans la sortie standard,
    agrégée et conservée par l'infrastructure.

    La longueur reste écrite : sans elle, la ligne ne servirait plus à répondre
    à « le message est-il parti, et n'est-il pas vide ? », sa seule raison
    d'être quand le contenu est masqué.
    """
    if settings.DEBUG:
        return f"{subject + ' — ' if subject else ''}{message}"
    return f"{REDACTED} ({len(message)} caractères)"


@dataclass
class NotificationResult:
    """
    Résultat d'un envoi, consigné dans `NotificationLog` par la tâche Celery.

    `provider` porte le nom court que le fournisseur se donne lui-même
    (« console », « fake_push », « smtp », « sms_mock »…). Il ne se déduit pas
    du nom de classe : `SmsConsoleProvider` s'annonce « sms_mock » parce que
    c'est ce qu'un opérateur doit lire dans le journal — que l'envoi était
    simulé, pas quelle classe l'a simulé. Laissé vide, la tâche retombe sur le
    nom de classe, ce qui préserve les appelants antérieurs au Ticket C.
    """

    success: bool
    provider: str = ""
    provider_message_id: str = ""
    error_message: str = ""


class NotificationProvider(ABC):
    """Interface abstraite pour les providers d'envoi (SMS, WhatsApp, push, email)."""

    @abstractmethod
    def send(self, recipient, message, subject=""):
        """Envoie un message. Retourne un NotificationResult."""
        raise NotImplementedError
