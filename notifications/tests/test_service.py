"""TOUPAC Notifications — Tests fumigènes (warm-up de la refonte notifs).

Deux ancrages minimaux pour la série de tickets à venir : le nouveau
comportement fail-tracé de send_notification() et le canal in-app.
"""
import pytest

from notifications.models import NotificationLog, NotificationTemplate
from notifications.services import NotificationService

pytestmark = pytest.mark.django_db


def test_send_notification_without_template_creates_failed_log(tenant_a):
    """Fix 1 — event sans template : NotificationLog(failed) au lieu de None (N-08)."""
    log = NotificationService.send_notification(
        tenant=tenant_a,
        event_code="inexistant",
        channel="sms",
        recipient="+221770000000",
        context_data={},
    )

    assert log is not None
    assert isinstance(log, NotificationLog)
    assert log.status == NotificationLog.Status.FAILED
    assert log.failure_reason.startswith("no_template:")
    assert log.content == ""


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
