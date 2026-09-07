"""
TOUPAC Notifications — Le push simulé réussit et se déclare simulé.

Ce qui est vérifié ici n'est pas qu'un message part — rien ne part — mais que
la trace laissée en base dise sans ambiguïté qu'il ne s'agissait pas d'un vrai
envoi FCM.
"""
import logging

from notifications.providers.fake_push import FakePushProvider

MESSAGE = "Votre bus part dans 30 minutes."


def test_the_fake_push_always_succeeds():
    """Le canal push ne doit pas encombrer les échecs tant qu'il est simulé."""
    result = FakePushProvider().send(recipient="device-token-abc", message=MESSAGE)

    assert result.success is True
    assert result.error_message == ""


def test_the_trace_announces_a_simulated_send():
    """
    Le nom et l'identifiant disent tous deux « simulé ».

    Sans quoi une ligne en base ne permettrait pas de distinguer, après coup, un
    envoi réel d'un envoi qui n'a jamais quitté le serveur.
    """
    result = FakePushProvider().send(recipient="device-token-abc", message=MESSAGE)

    assert result.provider == "fake_push"
    assert result.provider_message_id.startswith("fake_fcm_")


def test_two_sends_do_not_share_an_identifier():
    provider = FakePushProvider()

    first = provider.send(recipient="device-a", message=MESSAGE)
    second = provider.send(recipient="device-b", message=MESSAGE)

    assert first.provider_message_id != second.provider_message_id


def test_the_send_is_visible_in_the_logs(caplog):
    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        FakePushProvider().send(
            recipient="device-token-abc", message=MESSAGE, subject="Départ",
        )

    assert "[FAKE-PUSH]" in caplog.text
    assert "device-token-abc" in caplog.text
