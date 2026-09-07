"""TOUPAC Notifications — Tests fumigènes (warm-up de la refonte notifs).

Deux ancrages minimaux pour la série de tickets à venir : le nouveau
comportement fail-tracé de send_notification() et le canal in-app.
"""
import pytest
from django.utils import timezone

from notifications.models import NotificationLog, NotificationTemplate
from notifications.services import NotificationService

pytestmark = pytest.mark.django_db


def test_send_notification_without_template_creates_failed_log(tenant_a):
    """
    Fix 1 — gabarit absent : NotificationLog(failed) au lieu d'un None muet (N-08).

    L'événement est désormais choisi dans le catalogue : depuis le Ticket B, un
    code inconnu lève `KeyError` au lieu de produire une trace — c'est un défaut
    de l'appelant, pas un incident de livraison. L'intention du test ne change
    pas : un gabarit manquant doit laisser une trace exploitable.
    """
    log = NotificationService.send_notification(
        tenant=tenant_a,
        event_code="notif.gps.vehicle_offline.v1",  # aucun gabarit seedé
        channel="email",  # canal déclaré par l'événement, mais sans gabarit
        recipient="ops@example.sn",
        context_data={
            "vehicle_label": "SN-2145-AZ",
            "last_seen_at": timezone.now(),
            "offline_minutes": 42,
        },
    )

    assert log is not None
    assert isinstance(log, NotificationLog)
    assert log.status == NotificationLog.Status.FAILED
    assert log.failure_reason.startswith("no_template:")
    assert log.content == ""


def test_send_notification_raises_on_an_unknown_event_code(tenant_a):
    """Un code hors catalogue est un défaut d'appelant : il remonte."""
    with pytest.raises(KeyError):
        NotificationService.send_notification(
            tenant=tenant_a, event_code="inexistant", channel="sms",
            recipient="+221770000000", context_data={},
        )


def test_in_app_channel_available_in_choices(tenant_a):
    """Fix 2 — le canal in-app existe dans l'enum et un template in_app est valide."""
    assert NotificationTemplate.Channel.IN_APP == "in_app"

    template = NotificationTemplate(
        tenant=tenant_a,
        event_code="test",
        channel=NotificationTemplate.Channel.IN_APP,
        language="fr",
        template_body="Bonjour {{ name }}",
    )
    template.full_clean()  # ne lève pas : le canal in_app est dans les choices
