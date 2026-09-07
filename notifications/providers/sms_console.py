"""
TOUPAC Notifications — SMS simulé, en attendant une passerelle réelle.

Le préfixe `[SMS-MOCK]` dans les journaux et le nom `sms_mock` consigné en base
disent la même chose : rien n'est parti. C'est le point de ce provider. Un SMS
coûte à l'envoi, et le canal est réservé aux codes de connexion — un mock muet
qui se ferait passer pour un vrai envoi laisserait croire à une exploitation
que la connexion fonctionne alors que personne ne reçoit rien.

Passerelle réelle au ticket dédié (Africa's Talking, Twilio, Orange SMS
Business), quand un compte et un budget existent.

Le masquage hors développement reprend la règle commune de `base.py` : ce
provider imprime en clair, il doit donc s'auto-restreindre dès qu'il quitte le
poste du développeur.
"""
import logging
import uuid

from .base import NotificationProvider, NotificationResult, loggable_body

logger = logging.getLogger("toupac.notifications")


class SmsConsoleProvider(NotificationProvider):
    """Mock SMS — n'envoie rien, l'annonce clairement."""

    def send(self, recipient, message, subject=""):
        message_id = f"sms_mock_{uuid.uuid4().hex[:16]}"
        logger.info(
            "[SMS-MOCK] → %s | %s | id=%s",
            recipient, loggable_body(message), message_id,
        )
        return NotificationResult(
            success=True, provider="sms_mock", provider_message_id=message_id,
        )
