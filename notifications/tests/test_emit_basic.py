"""
TOUPAC Notifications — `emit()`, parcours nominal et contrat d'entrée.

Le service ne remonte que deux erreurs à l'appelant : un code d'événement
inconnu et un contexte non conforme. Ce sont des défauts de programme, pas des
incidents de livraison — les faire échouer bruyamment est le seul moyen de les
voir avant la production.
"""
import pytest

from notifications.catalog import get_event
from notifications.models import Notification, NotificationLog
from notifications.services import EmitResult, NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_templates_for_all_channels,
    resolver_returning,
    resolver_returning_nothing,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

TICKET_RESOLVER = get_event(TICKET_EVENT).resolver_key


def test_emit_returns_an_emit_result(tenant_a, client_fatou):
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert isinstance(result, EmitResult)
    assert result.idempotency_hit is False
    assert result.skipped_no_recipient is False


def test_emit_creates_one_notification_and_one_log_per_channel(tenant_a, client_fatou):
    """
    Un item de centre d'alertes par personne, un envoi par canal.

    La `Notification` matérialise « ce qui est arrivé au destinataire » ; chaque
    `NotificationLog` est une tentative de le lui dire par un chemin donné.
    """
    make_templates_for_all_channels()
    channel_count = len(get_event(TICKET_EVENT).default_channels)

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert result.notifications_created == 1
    assert result.logs_created == channel_count
    assert Notification.objects.filter(recipient_user=client_fatou).count() == 1
    assert NotificationLog.objects.count() == channel_count


def test_every_log_is_attached_to_the_notification(tenant_a, client_fatou):
    """
    Les envois se rattachent tous à l'item du centre d'alertes.

    C'est ce qui permet de répondre « par où a-t-on tenté de la joindre ? » sans
    recouper sur l'horodatage.
    """
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    notification = Notification.objects.get()
    assert notification.delivery_attempts.count() == NotificationLog.objects.count()


def test_emit_records_the_event_priority_on_the_notification(tenant_a, client_fatou):
    """La priorité vient du catalogue, jamais du gabarit."""
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert Notification.objects.get().priority == get_event(TICKET_EVENT).priority.value


def test_emit_notifies_every_resolved_recipient(tenant_a, client_fatou, user_dispatcher_a):
    """Un événement diffusé à plusieurs personnes produit un item par personne."""
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou, user_dispatcher_a)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert result.notifications_created == 2
    assert set(Notification.objects.values_list("recipient_user", flat=True)) == {
        client_fatou.pk, user_dispatcher_a.pk,
    }


def test_emit_raises_on_an_unknown_event_code(tenant_a):
    with pytest.raises(KeyError, match="Unknown event code"):
        NotificationService.emit(event_code="notif.nope.nope.v1", context={}, tenant=tenant_a)


def test_emit_raises_on_an_invalid_context(tenant_a):
    """Le contexte est un contrat déclaré par le catalogue, pas une suggestion."""
    with pytest.raises(ValueError, match="missing required variable"):
        NotificationService.emit(
            event_code=TICKET_EVENT, context={"reference": "REF-001"}, tenant=tenant_a,
        )


def test_emit_creates_nothing_when_the_context_is_invalid(tenant_a):
    make_templates_for_all_channels()

    with pytest.raises(ValueError):
        NotificationService.emit(event_code=TICKET_EVENT, context={}, tenant=tenant_a)

    assert Notification.objects.count() == 0
    assert NotificationLog.objects.count() == 0


def test_emit_skips_when_the_resolver_returns_nobody(tenant_a):
    """Personne à prévenir est un résultat légitime, pas un échec."""
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning_nothing):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert result.skipped_no_recipient is True
    assert result.logs_created == 0
    assert result.logs_failed == 0
    assert NotificationLog.objects.count() == 0


def test_emit_restricts_to_the_requested_channels(tenant_a, client_fatou):
    """
    Sans restriction, un envoi demandé sur un canal partirait sur tous.

    C'est ce qui ferait payer trois messages pour un code de connexion demandé
    par e-mail.
    """
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
            channels=["email"],
        )

    assert result.logs_created == 1
    assert list(NotificationLog.objects.values_list("channel", flat=True)) == ["email"]


def test_emit_traces_a_channel_the_event_does_not_declare(tenant_a, client_fatou):
    """Demander un canal absent de l'événement ne doit pas être un silence."""
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
            channels=["sms"],  # notif.ticket.issued.v1 ne déclare pas le SMS
        )

    assert result.logs_created == 0
    assert result.logs_failed == 1
    assert result.failure_reasons[0].startswith("channel_not_declared:")


def test_emit_result_is_json_serialisable(tenant_a, client_fatou):
    """Le compte rendu part dans les journaux applicatifs : il doit se sérialiser."""
    import json

    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert json.loads(json.dumps(result.as_dict()))["logs_created"] == result.logs_created


def test_emit_works_without_any_http_request(tenant_a, client_fatou):
    """
    Le service ne dépend d'aucun contexte de requête.

    Il tourne dans une tâche Celery et dans un script de rattrapage, où il n'y a
    ni `request.tenant` ni utilisateur connecté — la compagnie est un argument.
    """
    make_templates_for_all_channels()

    with temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)):
        result = NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )

    assert result.logs_created > 0
