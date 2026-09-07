"""TOUPAC Notifications — Provider de développement, écrit dans les logs Django."""
import logging

from django.conf import settings

from .base import NotificationProvider, NotificationResult

logger = logging.getLogger("toupac.notifications")


class ConsoleProvider(NotificationProvider):
    """
    Provider de développement — affiche les notifications dans les logs.

    Il n'envoie rien : il sert à lire le message rendu sans installer de
    passerelle. C'est aussi, faute de mieux, le provider utilisé partout tant
    que la fabrique par canal n'existe pas (Ticket C) — y compris en production,
    où il ne délivre donc rien.

    D'où la coupure ci-dessous : hors développement, le corps du message n'est
    pas écrit. Un code de connexion, un QR de billet ou un montant se
    retrouveraient sinon en clair dans la sortie standard, agrégée et conservée
    par l'infrastructure — une fuite silencieuse, sans rapport avec le canal
    d'envoi ni avec les masques de confidentialité, qui ne s'appliquent qu'au
    rendu poussé.

    Ce qui reste journalisé — destinataire, canal, longueur — suffit à constater
    qu'un envoi a eu lieu sans en révéler le contenu.
    """

    #: Ce que l'on écrit à la place du message hors développement.
    REDACTED = "[contenu masqué hors développement]"

    def send(self, recipient, message, subject=""):
        if settings.DEBUG:
            body = f"{subject + ' — ' if subject else ''}{message}"
        else:
            body = f"{self.REDACTED} ({len(message)} caractères)"

        logger.info("[NOTIFICATION] → %s: %s", recipient, body)
        return NotificationResult(success=True, provider_message_id="console")
