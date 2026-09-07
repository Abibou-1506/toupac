"""
TOUPAC Notifications — L'e-mail passe par la mécanique standard de Django.

Aucun serveur n'est joint. Django substitue de lui-même un backend en mémoire
pendant les tests, et `mailoutbox` — fixture de pytest-django — garantit cette
substitution puis vide la boîte entre deux tests. Les deux cas d'échec
ci-dessous imposent au contraire leur backend par `override_settings`, chacun
simulant une défaillance précise sans jamais ouvrir de connexion.
"""
import logging

import pytest
from django.core.mail.backends.base import BaseEmailBackend
from django.test import override_settings

from notifications.providers.email_smtp import DEFAULT_SUBJECT, EmailSmtpProvider

MESSAGE = "Votre billet REF-001 est confirmé."


class UnreachableServerBackend(BaseEmailBackend):
    """Backend qui lève, comme le ferait un serveur SMTP injoignable."""

    def send_messages(self, email_messages):
        raise ConnectionRefusedError("serveur SMTP injoignable")


class NoRecipientAcceptedBackend(BaseEmailBackend):
    """Backend qui n'accepte aucun destinataire sans pour autant lever."""

    def send_messages(self, email_messages):
        return 0


# ─── L'envoi nominal ───

def test_the_message_goes_through_django_mail(mailoutbox):
    result = EmailSmtpProvider().send(
        recipient="fatou@example.sn", message=MESSAGE, subject="Votre billet",
    )

    assert result.success is True
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["fatou@example.sn"]
    assert mailoutbox[0].subject == "Votre billet"
    assert mailoutbox[0].body == MESSAGE


def test_the_trace_names_the_provider_and_carries_a_reference(mailoutbox):
    result = EmailSmtpProvider().send(recipient="fatou@example.sn", message=MESSAGE)

    assert result.provider == "smtp"
    assert result.provider_message_id.startswith("smtp_")


def test_a_missing_subject_gets_a_neutral_one(mailoutbox):
    """Un e-mail sans objet finit en indésirable dans bien des messageries."""
    EmailSmtpProvider().send(recipient="fatou@example.sn", message=MESSAGE)

    assert mailoutbox[0].subject == DEFAULT_SUBJECT


@override_settings(DEFAULT_FROM_EMAIL="notifications@toupac.sn")
def test_the_sender_comes_from_the_settings(mailoutbox):
    EmailSmtpProvider().send(recipient="fatou@example.sn", message=MESSAGE)

    assert mailoutbox[0].from_email == "notifications@toupac.sn"


def test_the_body_never_reaches_the_logs(caplog, mailoutbox):
    """
    Le message part vraiment : la trace n'a pas à le recopier.

    Le sujet, lui, est écrit — il dit quelle notification est partie, les
    gabarits plaçant codes et QR dans le corps.
    """
    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        EmailSmtpProvider().send(
            recipient="fatou@example.sn", message=MESSAGE, subject="Votre billet",
        )

    assert MESSAGE not in caplog.text
    assert "fatou@example.sn" in caplog.text
    assert "Votre billet" in caplog.text


# ─── Les défaillances ───

@override_settings(
    EMAIL_BACKEND="notifications.tests.test_provider_email_smtp.UnreachableServerBackend",
)
def test_a_server_failure_is_propagated_not_swallowed():
    """
    Le provider ne rattrape pas : c'est la tâche qui décide de réessayer.

    Rattraper ici transformerait une panne passagère en échec définitif, et
    priverait le canal e-mail de ses trois réessais.
    """
    with pytest.raises(ConnectionRefusedError):
        EmailSmtpProvider().send(recipient="fatou@example.sn", message=MESSAGE)


@override_settings(
    EMAIL_BACKEND="notifications.tests.test_provider_email_smtp.NoRecipientAcceptedBackend",
)
def test_a_refused_recipient_is_a_failure_not_an_exception():
    """
    Un backend qui rend zéro n'est pas en panne : il refuse. La distinction
    compte, elle sépare ce qui mérite un réessai de ce qui n'en mérite pas.
    """
    result = EmailSmtpProvider().send(recipient="inconnu@example.sn", message=MESSAGE)

    assert result.success is False
    assert result.error_message
