"""
TOUPAC Notifications — Le SMS simulé s'annonce, et se tait hors développement.

Deux exigences distinctes se croisent sur ce provider :

- Il ne doit jamais laisser croire qu'un SMS est parti. Le canal est réservé aux
  codes de connexion ; une exploitation qui croirait la connexion fonctionnelle
  alors que personne ne reçoit rien perdrait un temps considérable.
- Il imprime en clair, donc il doit s'auto-restreindre hors développement. Le
  canal SMS ne transporte que des codes à usage unique : c'est précisément ce
  qu'il ne faut pas écrire dans une sortie standard conservée.
"""
import logging

from notifications.providers.base import REDACTED
from notifications.providers.sms_console import SmsConsoleProvider

SECRET = "482913"
MESSAGE = f"Votre code de connexion TOUPAC est {SECRET}."


def send_and_capture(caplog, settings, *, debug):
    settings.DEBUG = debug
    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        result = SmsConsoleProvider().send(recipient="+221770000001", message=MESSAGE)
    return result, caplog.text


def test_the_body_is_readable_in_development(caplog, settings):
    """Lire le code dans les logs est la raison d'être du mock en dev."""
    result, output = send_and_capture(caplog, settings, debug=True)

    assert result.success is True
    assert SECRET in output


def test_the_body_is_withheld_outside_development(caplog, settings):
    _, output = send_and_capture(caplog, settings, debug=False)

    assert SECRET not in output
    assert MESSAGE not in output
    assert REDACTED in output


def test_the_recipient_and_length_stay_visible(caplog, settings):
    """Constater qu'un envoi a eu lieu doit rester possible sans le lire."""
    _, output = send_and_capture(caplog, settings, debug=False)

    assert "+221770000001" in output
    assert str(len(MESSAGE)) in output


def test_the_simulation_is_announced_in_both_modes(caplog, settings):
    for debug in (True, False):
        caplog.clear()
        result, output = send_and_capture(caplog, settings, debug=debug)

        assert "[SMS-MOCK]" in output
        assert result.provider == "sms_mock"
        assert result.provider_message_id.startswith("sms_mock_")
