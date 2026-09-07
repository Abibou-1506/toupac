"""
TOUPAC Notifications — Confidentialité asymétrique par canal (N-05).

Le masque ne supprime pas une information, il **diffère** sa lecture vers un
canal où le destinataire aura prouvé son identité. Un billet s'annonce sur
l'écran verrouillé et se lit dans l'application.

Le corollaire est essentiel et se teste : là où il n'y a pas d'« ailleurs » —
SMS, WhatsApp, qui sont la livraison même — masquer détruirait le message.
"""
import pytest

from notifications.catalog import get_event
from notifications.channels import Channel
from notifications.models import NotificationLog
from notifications.rendering import (
    CHANNELS_FULL_PAYLOAD,
    CHANNELS_MASKING_APPLIED,
    MASK_PLACEHOLDER,
)
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_templates_for_all_channels,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

SECRET = "SECRET-QR-PAYLOAD"
TICKET_RESOLVER = get_event(TICKET_EVENT).resolver_key


@pytest.fixture
def emitted(tenant_a, client_fatou):
    """Émet le billet sur tous ses canaux et rend les envois par canal."""
    make_templates_for_all_channels()
    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(qr_payload=SECRET),
            tenant=tenant_a,
        )
    return {log.channel: log for log in NotificationLog.objects.all()}


def test_the_event_declares_the_variable_as_confidential():
    """Sans cette déclaration, le reste du fichier ne testerait rien."""
    assert "qr_payload" in get_event(TICKET_EVENT).confidentiality_masks


def test_push_masks_the_confidential_variable(emitted):
    """Un aperçu sur écran verrouillé ne doit pas livrer le billet."""
    push = emitted[Channel.PUSH]

    assert SECRET not in push.content
    assert MASK_PLACEHOLDER in push.content


def test_in_app_receives_the_full_payload(emitted):
    """Le destinataire a ouvert son application : il a prouvé qui il est."""
    assert SECRET in emitted[Channel.IN_APP].content


def test_email_receives_the_full_payload(emitted):
    assert SECRET in emitted[Channel.EMAIL].content


def test_the_notification_item_keeps_the_full_payload(emitted, client_fatou):
    """
    L'item du centre d'alertes est rendu depuis le canal in-app.

    S'il portait la version masquée, l'utilisateur ouvrirait son application
    pour y trouver `***` — le masque aurait supprimé au lieu de différer.
    """
    from notifications.models import Notification

    assert SECRET in Notification.objects.get(recipient_user=client_fatou).body


def test_sms_delivers_the_one_time_code_unmasked(tenant_a, client_fatou):
    """
    Le canal de livraison ne masque pas ce qu'il est chargé de livrer.

    `notif.auth.otp_signin.v1` déclare `otp` comme variable sensible — pour que
    l'aperçu poussé ne l'affiche pas. Appliquer ce masque au SMS enverrait
    « votre code est *** » et rendrait la connexion impossible.
    """
    otp_event = "notif.auth.otp_signin.v1"
    assert "otp" in get_event(otp_event).confidentiality_masks
    make_templates_for_all_channels(otp_event, template_body="Code : {{ otp }}")

    with temporary_resolver(get_event(otp_event).resolver_key, resolver_returning(client_fatou)):
        NotificationService.emit(
            event_code=otp_event, context={"otp": "123456", "expires_in_minutes": 5},
            tenant=tenant_a, channels=["sms"],
        )

    assert "123456" in NotificationLog.objects.get(channel="sms").content


def test_masking_applies_only_to_the_preview_channel():
    """Le partage des canaux est explicite et exhaustif."""
    assert CHANNELS_MASKING_APPLIED == {Channel.PUSH}
    assert CHANNELS_MASKING_APPLIED | CHANNELS_FULL_PAYLOAD == set(Channel)
    assert CHANNELS_MASKING_APPLIED & CHANNELS_FULL_PAYLOAD == set()


def test_non_confidential_variables_survive_the_mask(emitted):
    """Le masque est chirurgical : il ne touche que ce qui est déclaré."""
    assert "REF-001" in emitted[Channel.PUSH].content


def test_the_title_is_masked_too(tenant_a, client_fatou):
    """Le titre s'affiche autant que le corps sur un écran verrouillé."""
    make_templates_for_all_channels(title_template="QR {{ qr_payload }}")

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(qr_payload=SECRET),
            tenant=tenant_a, channels=["push", "in_app"],
        )

    from notifications.models import Notification

    # L'item in-app conserve la valeur ; c'est le rendu poussé qui la masque.
    assert SECRET in Notification.objects.get().title
    push_body = NotificationLog.objects.get(channel="push").content
    assert SECRET not in push_body
