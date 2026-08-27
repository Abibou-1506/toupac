"""TOUPAC Notifications — Interface abstraite des providers d'envoi."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationResult:
    success: bool
    provider_message_id: str = ""
    error_message: str = ""


class NotificationProvider(ABC):
    """Interface abstraite pour les providers d'envoi (SMS, WhatsApp, push, email)."""

    @abstractmethod
    def send(self, recipient, message, subject=""):
        """Envoie un message. Retourne un NotificationResult."""
        raise NotImplementedError
