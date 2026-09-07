"""
TOUPAC Notifications — L'ancienne fonction d'envoi, conservée le temps du refactor.

`send_notification()` reste disponible et délègue au nouveau service. C'est ce
qui permet de refondre le cœur sans toucher à la connexion par code, dont
dépend chaque utilisateur. Elle avertit à chaque appel, et disparaîtra au
Ticket F avec ses derniers appelants.

L'adaptateur fait deux choses que le nouveau service ne devine pas : il
restreint l'émission au canal demandé, et il livre tout de suite.
"""
import warnings

import pytest

from notifications.models import NotificationLog
from notifications.services import NotificationService
from notifications.tests.emit_helpers import make_template

pytestmark = pytest.mark.django_db

OTP_EVENT = "notif.auth.otp_signin.v1"
OTP_CONTEXT = {"otp": "123456", "expires_in_minutes": 5}


def send_legacy(tenant, channel="email", recipient="fatou@example.sn", **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return NotificationService.send_notification(
            tenant=tenant, event_code=OTP_EVENT, channel=channel,
            recipient=recipient, context_data=OTP_CONTEXT, **kwargs,
        )


def test_calling_it_warns():
    with pytest.warns(DeprecationWarning, match="emit"):
        with pytest.raises(Exception):  # noqa: B017 — l'avertissement précède tout traitement
            NotificationService.send_notification(
                tenant=None, event_code="inexistant", channel="email",
                recipient="x@example.sn", context_data={},
            )


def test_it_still_delivers(tenant_a):
    """Le contrat rendu à ses appelants : un envoi effectué, pas seulement mis en file."""
    make_template(OTP_EVENT, "email", template_body="Code : {{ otp }}")

    log = send_legacy(tenant_a)

    assert log is not None
    assert log.status == NotificationLog.Status.SENT
    assert log.sent_at is not None
    assert "123456" in log.content


def test_it_still_traces_a_missing_template(tenant_a):
    """Le comportement fail-tracé du warm-up est conservé."""
    log = send_legacy(tenant_a)

    assert log.status == NotificationLog.Status.FAILED
    assert log.failure_reason.startswith("no_template:")


def test_it_sends_on_the_requested_channel_only(tenant_a):
    """
    Sans restriction, un code demandé par e-mail partirait aussi en SMS et sur
    WhatsApp — trois messages facturés pour un seul demandé.
    """
    for channel in ("in_app", "email", "sms", "whatsapp"):
        make_template(OTP_EVENT, channel, template_body="Code : {{ otp }}")

    send_legacy(tenant_a, channel="email")

    assert list(NotificationLog.objects.values_list("channel", flat=True)) == ["email"]


def test_two_recipients_getting_the_same_code_are_not_deduplicated(tenant_a):
    """
    Le destinataire entre dans la clé d'idempotence.

    Sans lui, deux personnes recevant par hasard le même code à la même seconde
    se dédupliqueraient l'une l'autre — et la seconde ne recevrait rien.
    """
    make_template(OTP_EVENT, "email", template_body="Code : {{ otp }}")

    send_legacy(tenant_a, recipient="fatou@example.sn")
    send_legacy(tenant_a, recipient="aicha@example.sn")

    assert NotificationLog.objects.count() == 2


def test_a_phone_recipient_is_recognised(tenant_a):
    make_template(OTP_EVENT, "sms", template_body="Code : {{ otp }}")

    log = send_legacy(tenant_a, channel="sms", recipient="+221771234567")

    assert log.status == NotificationLog.Status.SENT
    assert log.recipient == "+221771234567"


def test_it_works_without_a_company(tenant_a):
    """La connexion par code n'a pas de compagnie : le client est global."""
    make_template(OTP_EVENT, "email", template_body="Code : {{ otp }}")

    log = send_legacy(tenant=None)

    assert log.status == NotificationLog.Status.SENT
    assert log.tenant is None
