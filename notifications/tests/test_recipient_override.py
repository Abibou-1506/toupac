"""
TOUPAC Notifications — Destinataire désigné en clair (`recipient_override`).

Un resolver répond à « qui prévenir ? » à partir du contexte métier. Le code de
connexion n'a pas cette question : on connaît l'adresse, et le compte n'est
justement pas encore la référence — c'est ce que l'utilisateur est en train de
prouver. L'override court-circuite donc la résolution.
"""
import pytest

from notifications.catalog import get_event
from notifications.models import Notification, NotificationLog
from notifications.services import NotificationService, RecipientTarget
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_template,
    resolver_raising,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

OTP_EVENT = "notif.auth.otp_signin.v1"
OTP_CONTEXT = {"otp": "123456", "expires_in_minutes": 5}


def test_an_email_target_bypasses_the_resolver(tenant_a):
    """Le resolver n'est même pas appelé : il lèverait si on y touchait."""
    make_template(OTP_EVENT, "email", template_body="Code : {{ otp }}")

    with temporary_resolver(
        get_event(OTP_EVENT).resolver_key, resolver_raising(AssertionError("appelé à tort")),
    ):
        result = NotificationService.emit(
            event_code=OTP_EVENT, context=OTP_CONTEXT, tenant=tenant_a,
            recipient_override=RecipientTarget(type="email", value="fatou@example.sn"),
            channels=["email"],
        )

    assert result.logs_created == 1
    assert NotificationLog.objects.get().recipient == "fatou@example.sn"


def test_a_phone_target_bypasses_the_resolver(tenant_a):
    make_template(OTP_EVENT, "sms", template_body="Code : {{ otp }}")

    result = NotificationService.emit(
        event_code=OTP_EVENT, context=OTP_CONTEXT, tenant=tenant_a,
        recipient_override=RecipientTarget(type="phone", value="+221771234567"),
        channels=["sms"],
    )

    assert result.logs_created == 1
    assert NotificationLog.objects.get().recipient == "+221771234567"


def test_an_override_without_an_account_creates_no_alert_item(tenant_a):
    """
    Sans compte, il n'y a pas de centre d'alertes où déposer l'item.

    L'envoi est tracé, mais orphelin — exactement le cas du code envoyé par SMS
    à quelqu'un qui n'est pas encore inscrit.
    """
    make_template(OTP_EVENT, "in_app", template_body="Code : {{ otp }}")

    result = NotificationService.emit(
        event_code=OTP_EVENT, context=OTP_CONTEXT, tenant=tenant_a,
        recipient_override=RecipientTarget(type="phone", value="+221771234567"),
        channels=["in_app"],
    )

    assert result.notifications_created == 0
    assert Notification.objects.count() == 0
    assert NotificationLog.objects.get().notification_id is None


def test_an_override_carrying_an_account_creates_the_alert_item(tenant_a, client_fatou):
    """Quand le compte est connu, l'item du centre d'alertes est créé."""
    make_template(OTP_EVENT, "in_app", template_body="Code : {{ otp }}")

    result = NotificationService.emit(
        event_code=OTP_EVENT, context=OTP_CONTEXT, tenant=tenant_a,
        recipient_override=RecipientTarget(
            type="email", value=client_fatou.email, user=client_fatou,
        ),
        channels=["in_app"],
    )

    assert result.notifications_created == 1
    assert Notification.objects.get().recipient_user == client_fatou


def test_an_override_skips_the_preference_check_when_no_account_is_known(tenant_a):
    """Sans compte, il n'y a aucune préférence à consulter — l'envoi part."""
    make_template(OTP_EVENT, "email", template_body="Code : {{ otp }}")

    result = NotificationService.emit(
        event_code=OTP_EVENT, context=OTP_CONTEXT, tenant=tenant_a,
        recipient_override=RecipientTarget(type="email", value="inconnu@example.sn"),
        channels=["email"],
    )

    assert result.logs_created == 1


def test_the_override_still_validates_the_context(tenant_a):
    """Court-circuiter la résolution ne dispense pas du contrat de contexte."""
    make_template(OTP_EVENT, "email")

    with pytest.raises(ValueError, match="missing required variable"):
        NotificationService.emit(
            event_code=OTP_EVENT, context={"otp": "123456"}, tenant=tenant_a,
            recipient_override=RecipientTarget(type="email", value="fatou@example.sn"),
        )


def test_the_override_still_honours_the_masks(tenant_a):
    """Un envoi poussé reste masqué, même vers un destinataire désigné."""
    make_template(TICKET_EVENT, "push")

    NotificationService.emit(
        event_code=TICKET_EVENT, context=ticket_context(qr_payload="SECRET"),
        tenant=tenant_a,
        recipient_override=RecipientTarget(type="email", value="fatou@example.sn"),
        channels=["push"],
    )

    assert "SECRET" not in NotificationLog.objects.get().content


def test_the_full_one_time_code_flow_still_works(api_client):
    """
    Bout en bout : la connexion par code passe toujours par ce chemin.

    C'est le test qui compte le plus de ce fichier — la refonte du service ne
    doit rien changer pour l'utilisateur qui se connecte.
    """
    import re
    from io import StringIO

    from django.core.management import call_command

    call_command("seed_notification_templates", stdout=StringIO())

    response = api_client.post(
        "/api/v1/auth/otp/request/", {"email": "fatou@example.sn"}, format="json",
    )
    assert response.status_code == 200

    log = NotificationLog.objects.filter(recipient="fatou@example.sn").latest("created_at")
    assert log.status == NotificationLog.Status.SENT
    code = re.search(r"\b(\d{6})\b", log.content).group(1)

    verified = api_client.post(
        "/api/v1/auth/otp/verify/",
        {"challenge_id": response.json()["challenge_id"], "code": code},
        format="json",
    )

    assert verified.status_code == 200
    assert verified.json()["access"]
