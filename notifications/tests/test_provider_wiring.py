"""
TOUPAC Notifications — Chaque canal atteint son propre provider, bout en bout.

Les tests par provider vérifient chacun sa mécanique isolément. Ceux-ci
vérifient le raccordement : qu'une émission traverse réellement la fabrique et
que la trace laissée en base nomme le fournisseur du canal, et non celui d'un
autre. C'est ce que le Ticket B ne pouvait pas faire — il n'existait qu'un
provider, appelé pour tous les canaux.
"""
import logging
from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from notifications.catalog import get_event
from notifications.models import NotificationLog
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_templates_for_all_channels,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

#: Le billet déclare push, in-app et e-mail — trois canaux, trois providers.
TICKET_PROVIDERS = {"push": "fake_push", "in_app": "console", "email": "smtp"}


def test_one_emission_reaches_three_distinct_providers(tenant_a, client_fatou, mailoutbox):
    """
    Trois canaux, trois fournisseurs — et un e-mail réellement remis à Django.

    Sans la fabrique, les trois lignes auraient porté « console ».
    """
    make_templates_for_all_channels(TICKET_EVENT)

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    logs = NotificationLog.objects.filter(event_code=TICKET_EVENT)
    assert {log.channel: log.provider for log in logs} == TICKET_PROVIDERS
    assert all(log.status == NotificationLog.Status.SENT for log in logs)
    assert len(mailoutbox) == 1


def test_the_identifier_kept_in_database_says_which_provider_answered(tenant_a, client_fatou):
    """
    Les préfixes distinguent une trace simulée d'une trace réelle.

    C'est ce qui permettra, le jour où les vraies passerelles arriveront, de
    savoir lesquelles des lignes existantes correspondaient à un envoi.
    """
    make_templates_for_all_channels(TICKET_EVENT)

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    by_channel = {
        log.channel: log.provider_message_id
        for log in NotificationLog.objects.filter(event_code=TICKET_EVENT)
    }
    assert by_channel["push"].startswith("fake_fcm_")
    assert by_channel["email"].startswith("smtp_")
    assert by_channel["in_app"] == "console"


# ─── La connexion par code, qui emprunte l'adaptateur historique ───

def test_the_one_time_code_by_sms_goes_through_the_sms_provider(caplog):
    """
    L'adaptateur déprécié impose son canal : le SMS ne doit pas partir en e-mail.

    Le Ticket B avait déjà failli perdre ce canal en route ; la fabrique ajoute
    un second endroit où l'erreur serait possible.
    """
    call_command("seed_notification_templates", stdout=StringIO())

    with caplog.at_level(logging.INFO, logger="toupac.notifications"):
        response = APIClient().post(
            "/api/v1/auth/otp/request/", {"phone": "+221770000042"}, format="json",
        )

    assert response.status_code == 200
    assert response.data["channel"] == "sms"

    log = NotificationLog.objects.get(recipient="+221770000042")
    assert log.channel == "sms"
    assert log.provider == "sms_mock"
    assert log.status == NotificationLog.Status.SENT
    assert "[SMS-MOCK]" in caplog.text


def test_the_one_time_code_by_email_is_actually_handed_to_django_mail(mailoutbox):
    """
    Le canal e-mail délivre désormais pour de bon.

    Jusqu'à ce ticket, la demande se déclarait réussie sans que rien ne parte —
    l'unique provider se contentait d'imprimer.
    """
    call_command("seed_notification_templates", stdout=StringIO())

    response = APIClient().post(
        "/api/v1/auth/otp/request/", {"email": "fatou@example.sn"}, format="json",
    )

    assert response.status_code == 200
    log = NotificationLog.objects.get(recipient="fatou@example.sn")
    assert log.provider == "smtp"
    assert log.status == NotificationLog.Status.SENT
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["fatou@example.sn"]
