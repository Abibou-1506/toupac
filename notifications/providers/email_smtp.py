"""
TOUPAC Notifications — Envoi d'e-mails par la mécanique standard de Django.

Seul provider de ce ticket qui délivre réellement. Il ne connaît pas SMTP : il
confie le message à `django.core.mail`, dont le backend est choisi par
`settings.EMAIL_BACKEND`. Passer de la console au vrai SMTP — SendGrid,
Postmark, SES — ne demande alors aucune ligne de code, seulement des variables
d'environnement.

Deux conséquences de ce choix méritent d'être connues :

- **Les exceptions ne sont pas rattrapées ici.** Un serveur SMTP injoignable
  remonte à la tâche Celery, qui applique la politique du canal e-mail (trois
  réessais espacés). Rattraper localement transformerait une panne passagère en
  échec définitif.
- **Le corps n'est jamais journalisé.** Inutile : contrairement aux mocks, le
  message part vraiment, et la trace n'a pas à le doubler. Le sujet, lui, est
  écrit — il dit quelle notification est partie sans révéler de secret, les
  gabarits plaçant les codes et les QR dans le corps.
"""
import logging
import uuid

from django.conf import settings
from django.core.mail import EmailMessage

from .base import NotificationProvider, NotificationResult

logger = logging.getLogger("toupac.notifications")

#: Sujet posé quand le gabarit n'en rend aucun — un e-mail sans objet part en
#: indésirable dans une bonne partie des messageries.
DEFAULT_SUBJECT = "TOUPAC — Notification"


class EmailSmtpProvider(NotificationProvider):
    """Envoi via `django.core.mail`, backend configuré par l'environnement."""

    def send(self, recipient, message, subject=""):
        effective_subject = subject or DEFAULT_SUBJECT
        email = EmailMessage(
            subject=effective_subject,
            body=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@toupac.sn"),
            to=[recipient],
        )
        sent = email.send(fail_silently=False)

        # SMTP ne rend pas d'identifiant de message exploitable via cette API.
        # Celui-ci n'est donc pas un identifiant fournisseur mais une référence
        # locale, de quoi relier une ligne de journal à une ligne en base. Les
        # vraies passerelles en rendront un plus tard, et le préfixe changera.
        message_id = f"smtp_{uuid.uuid4().hex[:16]}"
        logger.info(
            "[EMAIL] → %s | sujet=%r | envoyés=%s | id=%s",
            recipient, effective_subject[:60], sent, message_id,
        )
        return NotificationResult(
            success=(sent == 1),
            provider="smtp",
            provider_message_id=message_id,
            error_message="" if sent == 1 else "le backend n'a accepté aucun destinataire",
        )
