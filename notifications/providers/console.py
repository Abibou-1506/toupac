"""TOUPAC Notifications — Provider de développement, écrit dans les logs Django."""
import logging

from .base import REDACTED, NotificationProvider, NotificationResult, loggable_body

logger = logging.getLogger("toupac.notifications")


class ConsoleProvider(NotificationProvider):
    """
    Provider de développement — affiche les notifications dans les logs.

    Il n'envoie rien : il sert à lire le message rendu sans installer de
    passerelle. Depuis le Ticket C, il ne sert plus qu'au canal in-app et de
    filet pour un canal absent du mapping — les autres ont leur propre provider.

    Le masquage hors développement reste néanmoins nécessaire : le filet peut se
    déclencher en production, et un code de connexion, un QR de billet ou un
    montant se retrouveraient alors en clair dans la sortie standard, agrégée et
    conservée par l'infrastructure. Fuite sans rapport avec les masques de
    confidentialité, qui ne portent que sur le rendu poussé.

    Ce qui reste journalisé — destinataire, canal, longueur — suffit à constater
    qu'un envoi a eu lieu sans en révéler le contenu.
    """

    #: Repris de `base.py`, où la règle est désormais commune aux trois
    #: providers qui impriment sans envoyer. Conservé ici comme alias : les
    #: tests s'y réfèrent, et l'attribut dit sur la classe ce qu'elle fait.
    REDACTED = REDACTED

    def send(self, recipient, message, subject=""):
        logger.info(
            "[NOTIFICATION] → %s: %s", recipient, loggable_body(message, subject),
        )
        return NotificationResult(
            success=True, provider="console", provider_message_id="console",
        )
