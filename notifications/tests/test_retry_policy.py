"""
TOUPAC Notifications — Réessais différenciés par canal (N-09).

Réessayer un push coûte une requête ; réessayer un SMS coûte un SMS. La
politique encode cette asymétrie, et le défaut prudent — aucun réessai —
s'applique à tout canal qu'on aurait oublié de déclarer.
"""
from unittest import mock

import pytest

from notifications.channels import Channel
from notifications.models import NotificationLog
from notifications.providers.base import NotificationResult
from notifications.retries import NO_RETRY, RETRY_POLICIES, get_retry_policy
from notifications.services import NotificationService
from notifications.tasks import send_notification_log
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_template,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db


# ─── La politique ───

def test_free_channels_retry_with_exponential_backoff():
    policy = get_retry_policy(Channel.PUSH)

    assert policy.max_retries == 3
    assert [policy.countdown_for(n) for n in range(3)] == [60, 120, 240]
    assert get_retry_policy(Channel.EMAIL).max_retries == 3


@pytest.mark.parametrize("channel", [Channel.SMS, Channel.WHATSAPP])
def test_billed_channels_never_retry(channel):
    """Réessayer un message facturé, c'est le payer deux fois."""
    assert get_retry_policy(channel).max_retries == 0


def test_in_app_never_retries():
    """Une écriture en base qui échoue est un défaut, pas un aléa réseau."""
    assert get_retry_policy(Channel.IN_APP).max_retries == 0


def test_an_unknown_channel_falls_back_to_no_retry():
    """Le défaut prudent s'applique à un canal ajouté sans entrée déclarée."""
    assert get_retry_policy("canal-inconnu") == NO_RETRY
    assert get_retry_policy("") == NO_RETRY


def test_every_declared_channel_has_a_policy():
    """Aucun canal du système ne doit dépendre du repli implicite."""
    assert set(RETRY_POLICIES) == set(Channel)


def test_policies_accept_channel_values_as_strings():
    """La tâche lit `log.channel`, qui est une chaîne."""
    assert get_retry_policy("push").max_retries == 3
    assert get_retry_policy("sms").max_retries == 0


# ─── Effet dans la tâche ───

#: Le billet ne passe pas par SMS (réservé aux codes) : les cas SMS s'appuient
#: donc sur l'événement de connexion, seul à déclarer ce canal.
OTP_EVENT = "notif.auth.otp_signin.v1"
OTP_CONTEXT = {"otp": "123456", "expires_in_minutes": 5}


def queue_one_log(tenant, recipient, channel, event_code=TICKET_EVENT, context=None):
    """Émet sur un seul canal et rend l'envoi resté en file."""
    from notifications.catalog import get_event

    make_template(event_code, channel, template_body="Message {{ otp }}{{ reference }}")
    with (
        temporary_resolver(get_event(event_code).resolver_key, resolver_returning(recipient)),
        mock.patch.object(NotificationService, "_enqueue"),  # on déclenche à la main
    ):
        NotificationService.emit(
            event_code=event_code, context=context or ticket_context(),
            tenant=tenant, channels=[channel],
        )
    return NotificationLog.objects.get(channel=channel)


def test_a_billed_channel_fails_on_the_first_refusal(tenant_a, client_fatou):
    """Sans réessai, le premier refus est définitif — et tracé comme tel."""
    log = queue_one_log(
        tenant_a, client_fatou, "sms", event_code=OTP_EVENT, context=OTP_CONTEXT,
    )

    provider = mock.Mock()
    provider.send.return_value = NotificationResult(success=False, error_message="refus")

    with mock.patch("notifications.tasks.get_provider", return_value=provider):
        send_notification_log(str(log.pk))

    log.refresh_from_db()
    assert log.status == NotificationLog.Status.FAILED
    assert log.failure_reason.startswith("provider_error:sms:")
    assert provider.send.call_count == 1


def test_a_successful_send_records_the_provider_and_timestamp(tenant_a, client_fatou):
    log = queue_one_log(tenant_a, client_fatou, "in_app")

    send_notification_log(str(log.pk))

    log.refresh_from_db()
    assert log.status == NotificationLog.Status.SENT
    assert log.provider == "console"
    assert log.provider_message_id
    assert log.sent_at is not None
    assert log.failure_reason == ""


def test_the_task_is_a_no_op_on_an_already_processed_log(tenant_a, client_fatou):
    """
    Rejouer la tâche ne renvoie rien.

    Celery peut livrer un message deux fois, et un opérateur peut relancer à la
    main : ni l'un ni l'autre ne doit produire un second message.
    """
    log = queue_one_log(tenant_a, client_fatou, "in_app")
    send_notification_log(str(log.pk))
    log.refresh_from_db()
    first_sent_at = log.sent_at

    provider = mock.Mock()
    with mock.patch("notifications.tasks.get_provider", return_value=provider):
        send_notification_log(str(log.pk))

    log.refresh_from_db()
    assert provider.send.call_count == 0
    assert log.sent_at == first_sent_at


def test_the_task_tolerates_a_deleted_log():
    """L'envoi a pu être purgé entre la mise en file et l'exécution."""
    import uuid

    send_notification_log(str(uuid.uuid4()))  # ne lève pas
