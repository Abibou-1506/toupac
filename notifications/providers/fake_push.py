"""
TOUPAC Notifications — Push simulé, en attendant Firebase.

Ce provider accepte tout et ne pousse rien. Il existe pour que la chaîne
complète — résolution, rendu, écriture, mise en file, consignation — se déroule
et se vérifie sans compte Firebase, plutôt que de laisser le canal push
échouer et polluer les traces d'échecs qui n'en sont pas.

Le vrai provider viendra quand trois choses seront réunies : un projet Firebase,
son compte de service en secret d'environnement, et des jetons FCM stockés
côté utilisateur. Le préfixe `fake_fcm_` de l'identifiant consigné évite entre
temps toute confusion en base : un envoi simulé se distingue d'un vrai envoi
par sa seule trace, sans avoir à connaître la configuration du jour.

Le corps est journalisé tronqué et sans garde `DEBUG`, contrairement aux mocks
console : ce provider n'est pas destiné à rester actif en production, et le
canal push est justement celui dont les masques de confidentialité (N-05)
retirent déjà les valeurs sensibles avant qu'elles n'arrivent ici.
"""
import logging
import uuid

from .base import NotificationProvider, NotificationResult

logger = logging.getLogger("toupac.notifications")


class FakePushProvider(NotificationProvider):
    """Mock FCM — réussit toujours, trace un identifiant reconnaissable."""

    def send(self, recipient, message, subject=""):
        message_id = f"fake_fcm_{uuid.uuid4().hex[:16]}"
        logger.info(
            "[FAKE-PUSH] → %s | sujet=%r | corps=%r | id=%s",
            recipient, subject[:60], message[:100], message_id,
        )
        return NotificationResult(
            success=True, provider="fake_push", provider_message_id=message_id,
        )
