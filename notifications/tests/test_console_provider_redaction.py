"""
TOUPAC Notifications — Le provider de développement ne divulgue pas hors dev.

`prod.py` journalise `toupac` à INFO. Sans garde-fou, chaque code de connexion,
chaque QR de billet et chaque montant partirait en clair dans la sortie
standard, agrégée et conservée par l'infrastructure.

Le masquage par canal (N-05) ne couvre pas ce cas : il porte sur le rendu poussé
vers l'utilisateur, pas sur ce que le serveur écrit sur lui-même.

Depuis le Ticket C, la règle vit dans `providers.base.loggable_body()` et vaut
pour les trois providers qui impriment sans envoyer. Le cas bout en bout ci-
dessous emprunte donc le canal SMS : c'est celui qui transporte réellement des
codes vers un provider qui les journalise, et donc le seul où un défaut de
masquage se traduirait par une fuite.
"""
import logging

import pytest

from notifications.providers.base import REDACTED
from notifications.providers.console import ConsoleProvider

pytestmark = pytest.mark.django_db

SECRET = "123456"
MESSAGE = f"Votre code de connexion est {SECRET}."


def send_and_capture(caplog, settings, *, debug):
    settings.DEBUG = debug
    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        result = ConsoleProvider().send(
            recipient="fatou@example.sn", message=MESSAGE, subject="Code TOUPAC",
        )
    return result, caplog.text


def test_the_body_is_visible_in_development(caplog, settings):
    """En dev, lire le message dans les logs est tout l'intérêt de ce provider."""
    result, output = send_and_capture(caplog, settings, debug=True)

    assert result.success is True
    assert SECRET in output
    assert "Code TOUPAC" in output


def test_the_body_is_withheld_outside_development(caplog, settings):
    result, output = send_and_capture(caplog, settings, debug=False)

    assert result.success is True
    assert SECRET not in output
    assert MESSAGE not in output
    assert ConsoleProvider.REDACTED in output


def test_the_subject_is_withheld_too(caplog, settings):
    """Un sujet porte souvent l'essentiel : « Votre billet pour Bamako »."""
    _, output = send_and_capture(caplog, settings, debug=False)

    assert "Code TOUPAC" not in output


def test_the_recipient_stays_visible(caplog, settings):
    """
    Constater qu'un envoi a eu lieu reste possible.

    Sans destinataire ni longueur, la ligne ne servirait plus à diagnostiquer
    « le message est-il parti ? ».
    """
    _, output = send_and_capture(caplog, settings, debug=False)

    assert "fatou@example.sn" in output
    assert str(len(MESSAGE)) in output


def test_the_one_time_code_does_not_reach_the_logs_in_production(caplog, settings):
    """
    Bout en bout : la demande de code ne divulgue rien hors développement.

    Par SMS, le canal où le code atteint réellement un provider qui journalise.
    """
    import re
    from io import StringIO

    from django.core.management import call_command
    from rest_framework.test import APIClient

    from notifications.models import NotificationLog

    call_command("seed_notification_templates", stdout=StringIO())
    settings.DEBUG = False

    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        response = APIClient().post(
            "/api/v1/auth/otp/request/", {"phone": "+221770000077"}, format="json",
        )

    assert response.status_code == 200
    log = NotificationLog.objects.get(recipient="+221770000077")
    assert log.status == NotificationLog.Status.SENT
    assert log.provider == "sms_mock"

    # Le code est bien rendu et conservé en base — mais absent de la sortie.
    code = re.search(r"\b(\d{6})\b", log.content).group(1)
    assert code not in caplog.text
    assert REDACTED in caplog.text
