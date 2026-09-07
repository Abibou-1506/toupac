"""
TOUPAC Notifications — Traçabilité symétrique des échecs (N-08).

Chaque façon d'échouer laisse une trace nommée. C'est la différence entre « les
clients ne reçoivent plus leurs billets » et « il manque le gabarit e-mail de
notif.ticket.issued.v1 en wolof » — la première est une enquête, la seconde un
correctif de dix minutes.

Le préfixe de `failure_reason` est le contrat : il se filtre en base sans lire
le message, qui peut évoluer.
"""
import pytest

from notifications.catalog import get_event
from notifications.models import NotificationLog
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_template,
    make_templates_for_all_channels,
    resolver_raising,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

TICKET_RESOLVER = get_event(TICKET_EVENT).resolver_key


def emit_with(resolver, tenant, **kwargs):
    with temporary_resolver(TICKET_RESOLVER, resolver):
        return NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant, **kwargs,
        )


def reasons_by_prefix(prefix):
    return NotificationLog.objects.filter(
        status=NotificationLog.Status.FAILED, failure_reason__startswith=prefix,
    )


def test_a_missing_template_is_traced(tenant_a, client_fatou):
    """Aucun gabarit créé : chaque canal laisse sa propre trace."""
    result = emit_with(resolver_returning(client_fatou), tenant_a)

    channel_count = len(get_event(TICKET_EVENT).default_channels)
    assert result.logs_failed == channel_count
    assert reasons_by_prefix("no_template:").count() == channel_count
    trace = reasons_by_prefix("no_template:").first()
    assert TICKET_EVENT in trace.failure_reason
    assert trace.content == ""
    assert trace.provider == ""
    assert trace.sent_at is None


def test_a_broken_template_is_traced(tenant_a, client_fatou):
    """
    Un gabarit à la syntaxe invalide échoue à la construction, pas au rendu.

    Attention au piège : `{{ non fermé` n'est pas une erreur pour Django, c'est
    du texte. Il faut un filtre ou une balise inconnus pour qu'il lève.
    """
    make_templates_for_all_channels(template_body="{{ reference|filtre_inexistant }}")

    result = emit_with(resolver_returning(client_fatou), tenant_a)

    assert result.logs_created == 0
    assert reasons_by_prefix("template_error:").exists()
    assert any(r.startswith("template_error:") for r in result.failure_reasons)


def test_an_unclosed_brace_is_not_an_error(tenant_a, client_fatou):
    """
    Django rend `{{ceci` littéralement — ce n'est pas une syntaxe invalide.

    Le noter en test évite qu'on écrive un jour un cas de figure qui ne
    reproduit pas ce qu'il croit reproduire.
    """
    make_templates_for_all_channels(template_body="{{ceci n'est pas une erreur")

    result = emit_with(resolver_returning(client_fatou), tenant_a)

    assert result.logs_created > 0
    assert not reasons_by_prefix("template_error:").exists()


def test_an_unimplemented_resolver_is_traced(tenant_a):
    """Les resolvers métier du Ticket E ne sont pas encore écrits : on le dit."""
    make_templates_for_all_channels()

    result = NotificationService.emit(
        event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
    )

    assert result.logs_created == 0
    assert result.failure_reasons == [f"resolver_unimplemented:{TICKET_RESOLVER}"]
    assert reasons_by_prefix("resolver_unimplemented:").exists()


def test_a_resolver_that_raises_is_traced(tenant_a):
    """Un resolver fautif ne fait pas échouer l'appelant métier."""
    make_templates_for_all_channels()

    result = emit_with(resolver_raising(ValueError("boum")), tenant_a)

    assert result.logs_created == 0
    trace = reasons_by_prefix("resolver_error:").get()
    assert TICKET_RESOLVER in trace.failure_reason
    assert "boum" in trace.failure_reason


def test_a_preference_violation_is_traced_and_still_delivers(tenant_a, client_fatou):
    """Déjà couvert côté préférences ; vérifié ici sous l'angle de la trace."""
    otp_event = "notif.auth.otp_signin.v1"
    make_templates_for_all_channels(otp_event, template_body="{{ otp }}")
    client_fatou.notification_preferences = {"otp": False}
    client_fatou.save(update_fields=["notification_preferences"])

    with temporary_resolver(
        get_event(otp_event).resolver_key, resolver_returning(client_fatou),
    ):
        result = NotificationService.emit(
            event_code=otp_event,
            context={"otp": "123456", "expires_in_minutes": 5},
            tenant=tenant_a,
        )

    assert result.logs_created > 0
    assert reasons_by_prefix("preference_violation:").exists()


def test_a_provider_failure_is_traced_after_the_last_retry(tenant_a, client_fatou):
    """
    Le fournisseur refuse : la trace arrive au bout des réessais.

    Le canal in-app n'en fait aucun (une écriture en base qui échoue est un
    bug, pas un aléa réseau) : la trace est donc immédiate.
    """
    from unittest import mock

    from notifications.providers.base import NotificationResult

    make_template(TICKET_EVENT, "in_app")

    failing = mock.Mock()
    failing.send.return_value = NotificationResult(
        success=False, error_message="passerelle injoignable",
    )

    with mock.patch("notifications.tasks.get_provider", return_value=failing):
        emit_with(resolver_returning(client_fatou), tenant_a, channels=["in_app"])

    trace = reasons_by_prefix("provider_error:").get()
    assert "in_app" in trace.failure_reason
    assert "passerelle injoignable" in trace.failure_reason
    assert trace.status == NotificationLog.Status.FAILED
    assert trace.sent_at is None


def test_failures_of_one_channel_do_not_stop_the_others(tenant_a, client_fatou):
    """
    Un gabarit manquant sur un canal n'empêche pas les autres de partir.

    C'est ce qui distingue une trace d'une exception : l'émission continue.
    """
    channels = [c.value for c in get_event(TICKET_EVENT).default_channels]
    for channel in channels[1:]:  # le premier reste sans gabarit
        make_template(TICKET_EVENT, channel)

    result = emit_with(resolver_returning(client_fatou), tenant_a)

    assert result.logs_created == len(channels) - 1
    assert result.logs_failed == 1
