"""
TOUPAC Notifications — La fabrique choisit le provider d'après les settings.

Le mapping est déclaratif pour deux raisons vérifiées ici : brancher une vraie
passerelle doit être un changement de configuration, et un canal oublié ne doit
pas faire échouer une émission.
"""
import pytest
from django.test import override_settings

from notifications.channels import Channel
from notifications.providers.console import ConsoleProvider
from notifications.providers.email_smtp import EmailSmtpProvider
from notifications.providers.factory import get_provider
from notifications.providers.fake_push import FakePushProvider
from notifications.providers.sms_console import SmsConsoleProvider
from notifications.providers.whatsapp_console import WhatsAppConsoleProvider

EXPECTED = {
    Channel.PUSH: FakePushProvider,
    Channel.EMAIL: EmailSmtpProvider,
    Channel.SMS: SmsConsoleProvider,
    Channel.WHATSAPP: WhatsAppConsoleProvider,
    Channel.IN_APP: ConsoleProvider,
}


@pytest.mark.parametrize(("channel", "expected"), EXPECTED.items())
def test_the_factory_returns_the_provider_declared_for_each_channel(channel, expected):
    assert isinstance(get_provider(channel), expected)


def test_every_declared_channel_is_mapped():
    """
    Aucun canal ne doit dépendre du repli.

    Ajouter un canal sans lui donner de provider le ferait taire silencieusement
    derrière la console — ce test transforme l'oubli en échec.
    """
    from django.conf import settings

    assert set(settings.NOTIFICATION_PROVIDERS) == {c.value for c in Channel}


def test_the_factory_accepts_a_plain_string_as_well_as_the_enum():
    """`NotificationLog.channel` rend une chaîne, pas un membre de l'énumération."""
    assert isinstance(get_provider("sms"), SmsConsoleProvider)


def test_an_unknown_channel_falls_back_to_the_console():
    """
    Le repli imprime plutôt que de lever.

    Une émission porte plusieurs canaux : faire échouer la fabrique priverait
    les autres d'un envoi qui n'avait aucune raison d'échouer.
    """
    assert isinstance(get_provider("canal-inconnu"), ConsoleProvider)
    assert isinstance(get_provider(""), ConsoleProvider)


@override_settings(NOTIFICATION_PROVIDERS={"sms": "notifications.providers.console.ConsoleProvider"})
def test_the_mapping_can_be_overridden_by_environment():
    """C'est tout l'intérêt du réglage : substituer sans toucher au code."""
    assert isinstance(get_provider("sms"), ConsoleProvider)


@override_settings(NOTIFICATION_PROVIDERS={})
def test_an_empty_mapping_leaves_every_channel_on_the_console():
    assert isinstance(get_provider("push"), ConsoleProvider)


def test_each_call_builds_a_fresh_instance():
    """
    Pas de cache — les providers sont sans état.

    Une instance partagée entre les fils d'un worker Celery serait un état
    commun à surveiller pour aucun gain mesurable.
    """
    first, second = get_provider("push"), get_provider("push")

    assert first is not second


@override_settings(NOTIFICATION_PROVIDERS={"sms": "notifications.providers.nexiste.PasDeClasse"})
def test_a_wrong_dotted_path_fails_loudly():
    """
    Une erreur de configuration doit se voir au premier envoi, pas se taire.

    Retomber sur la console masquerait la faute de frappe et laisserait croire
    que la passerelle est branchée.
    """
    with pytest.raises(ImportError):
        get_provider("sms")
