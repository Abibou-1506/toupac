"""TOUPAC Notifications — Provider de dev, écrit dans les logs Django."""
import logging

from .base import NotificationProvider, NotificationResult

logger = logging.getLogger("toupac.notifications")


class ConsoleProvider(NotificationProvider):
    """Provider de dev — écrit les notifications dans les logs Django."""

    def send(self, recipient, message, subject=""):
        logger.info(f"[NOTIFICATION] → {recipient}: {subject + ' — ' if subject else ''}{message}")
        return NotificationResult(success=True, provider_message_id="console")
