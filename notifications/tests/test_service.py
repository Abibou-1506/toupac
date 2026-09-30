"""
TOUPAC Notifications — Tests fumigènes (warm-up de la refonte notifs).

Deux ancrages minimaux, hérités du warm-up : la trace d'un gabarit manquant, et
l'existence du canal in-app. Depuis le Ticket F, ils passent directement par
`emit()` — l'adaptateur `send_notification` n'existe plus.
"""
import pytest
from django.utils import timezone

from notifications.models import NotificationLog, NotificationTemplate
from notifications.services import NotificationService, RecipientTarget

pytestmark = pytest.mark.django_db


def test_emit_without_template_traces_a_failed_log(tenant_a):
    """Gabarit absent : `NotificationLog(failed)` plutôt qu'un `None` muet (N-08)."""
    result = NotificationService.emit(
        event_code="notif.gps.vehicle_offline.v1",  # aucun gabarit seedé
        context={
            "vehicle_label": "SN-2145-AZ",
            "last_seen_at": timezone.now(),
            "offline_minutes": 42,
        },
        tenant=tenant_a,
        recipient_override=RecipientTarget(
            type="email", value="ops@example.sn", user=None,
        ),
        channels=["email"],
    )

    assert result.logs_failed > 0
    log = NotificationLog.objects.filter(status=NotificationLog.Status.FAILED).first()
    assert log is not None
    assert log.failure_reason.startswith("no_template:")
    assert log.content == ""


def test_emit_raises_on_an_unknown_event_code(tenant_a):
    """Un code hors catalogue est un défaut d'appelant : il remonte."""
    with pytest.raises(KeyError):
        NotificationService.emit(
            event_code="inexistant", context={}, tenant=tenant_a,
        )


def test_in_app_channel_available_in_choices(tenant_a):
    """Le canal in-app existe dans l'enum et un template `in_app` est valide."""
    assert NotificationTemplate.Channel.IN_APP == "in_app"

    template = NotificationTemplate(
        tenant=tenant_a,
        event_code="test",
        channel=NotificationTemplate.Channel.IN_APP,
        language="fr",
        template_body="Bonjour {{ name }}",
    )
    template.full_clean()  # ne lève pas : le canal in_app est dans les choices
