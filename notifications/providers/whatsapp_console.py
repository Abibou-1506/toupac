"""
TOUPAC Notifications — WhatsApp simulé, en attendant une passerelle réelle.

Même parti que le mock SMS : `[WHATSAPP-MOCK]` et `whatsapp_mock` annoncent
qu'aucun message n'est parti, plutôt que de laisser croire le contraire.

Trois contraintes à connaître avant de câbler la vraie passerelle (Twilio
WhatsApp, Meta Cloud API), car elles ne se découvrent pas au moment du
branchement :

- Meta impose des **gabarits pré-approuvés** pour tout message à l'initiative de
  l'entreprise. Seule une réponse dans les vingt-quatre heures suivant un
  message de l'utilisateur y échappe. Les gabarits TOUPAC devront donc être
  soumis avant, et leur libellé figé côté Meta.
- Le **coût par message** est d'un tout autre ordre qu'un SMS, et varie selon
  le pays de destination.
- La **latence** est plus dispersée. La politique de réessai du canal reste
  aujourd'hui alignée sur celle du SMS — aucun réessai — et méritera d'être
  rediscutée à ce moment-là, pas maintenant.

Masquage hors développement par la règle commune de `base.py`.
"""
import logging
import uuid

from .base import NotificationProvider, NotificationResult, loggable_body

logger = logging.getLogger("toupac.notifications")


class WhatsAppConsoleProvider(NotificationProvider):
    """Mock WhatsApp — n'envoie rien, l'annonce clairement."""

    def send(self, recipient, message, subject=""):
        message_id = f"whatsapp_mock_{uuid.uuid4().hex[:16]}"
        logger.info(
            "[WHATSAPP-MOCK] → %s | %s | id=%s",
            recipient, loggable_body(message), message_id,
        )
        return NotificationResult(
            success=True, provider="whatsapp_mock", provider_message_id=message_id,
        )
