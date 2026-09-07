"""
TOUPAC Notifications — Le WhatsApp simulé suit la même règle que le SMS.

Même canal facturé, mêmes contenus sensibles, donc mêmes deux exigences : ne
jamais se faire passer pour un envoi réel, et ne rien imprimer en clair hors
développement.
"""
import logging

from notifications.providers.base import REDACTED
from notifications.providers.whatsapp_console import WhatsAppConsoleProvider

SECRET = "715204"
MESSAGE = f"Votre code de connexion TOUPAC est {SECRET}."


def send_and_capture(caplog, settings, *, debug):
    settings.DEBUG = debug
    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        result = WhatsAppConsoleProvider().send(
            recipient="+221770000001", message=MESSAGE,
        )
    return result, caplog.text


def test_the_body_is_readable_in_development(caplog, settings):
    result, output = send_and_capture(caplog, settings, debug=True)

    assert result.success is True
    assert SECRET in output


def test_the_body_is_withheld_outside_development(caplog, settings):
    _, output = send_and_capture(caplog, settings, debug=False)

    assert SECRET not in output
    assert REDACTED in output
    assert "+221770000001" in output


def test_the_simulation_is_announced_in_both_modes(caplog, settings):
    for debug in (True, False):
        caplog.clear()
        result, output = send_and_capture(caplog, settings, debug=debug)

        assert "[WHATSAPP-MOCK]" in output
        assert result.provider == "whatsapp_mock"
        assert result.provider_message_id.startswith("whatsapp_mock_")
