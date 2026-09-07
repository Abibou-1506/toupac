"""
TOUPAC Notifications — Préférences du destinataire (N-02).

Deux régimes. Un refus ordinaire est respecté en silence : c'est un choix, pas
un incident. Un refus portant sur une catégorie qui ne se refuse pas — code de
connexion, sécurité, exploitation critique — est une incohérence : on trace, et
on envoie quand même. Retenir un code de connexion parce qu'une préférence
corrompue dit « non » enfermerait l'utilisateur dehors.
"""
import pytest

from notifications.catalog import get_event
from notifications.models import NotificationLog
from notifications.preferences import (
    CATEGORY_CRITICAL_OPS,
    CATEGORY_MARKETING,
    CATEGORY_OTP,
    CATEGORY_SECURITY,
    NEVER_OPT_OUT,
)
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    make_templates_for_all_channels,
    resolver_returning,
    temporary_resolver,
)

pytestmark = pytest.mark.django_db

MARKETING_EVENT = "notif.marketing.promo.v1"
MARKETING_CONTEXT = {"campaign_label": "Promo rentrée"}

OTP_EVENT = "notif.auth.otp_signin.v1"
OTP_CONTEXT = {"otp": "123456", "expires_in_minutes": 5}


def emit(event_code, context, tenant, recipients):
    resolver_key = get_event(event_code).resolver_key
    with temporary_resolver(resolver_key, resolver_returning(*recipients)):
        return NotificationService.emit(
            event_code=event_code, context=context, tenant=tenant,
        )


def test_an_opted_out_recipient_is_skipped_silently(tenant_a, client_fatou):
    """Un refus respecté ne laisse aucune trace : ce n'est pas un incident."""
    make_templates_for_all_channels(MARKETING_EVENT)
    client_fatou.notification_preferences = {CATEGORY_MARKETING: False}
    client_fatou.save(update_fields=["notification_preferences"])

    result = emit(MARKETING_EVENT, MARKETING_CONTEXT, tenant_a, [client_fatou])

    assert result.logs_created == 0
    assert result.logs_failed == 0
    assert NotificationLog.objects.count() == 0


def test_an_absent_preference_means_opted_in(tenant_a, client_fatou):
    """Clé absente = accord : on n'exige pas un consentement jamais demandé."""
    make_templates_for_all_channels(MARKETING_EVENT)
    assert client_fatou.notification_preferences == {}

    result = emit(MARKETING_EVENT, MARKETING_CONTEXT, tenant_a, [client_fatou])

    assert result.logs_created > 0


def test_an_explicit_opt_in_is_honoured(tenant_a, client_fatou):
    make_templates_for_all_channels(MARKETING_EVENT)
    client_fatou.notification_preferences = {CATEGORY_MARKETING: True}
    client_fatou.save(update_fields=["notification_preferences"])

    result = emit(MARKETING_EVENT, MARKETING_CONTEXT, tenant_a, [client_fatou])

    assert result.logs_created > 0


def test_one_recipient_opting_out_does_not_affect_the_others(
    tenant_a, client_fatou, client_aicha,
):
    make_templates_for_all_channels(MARKETING_EVENT)
    client_fatou.notification_preferences = {CATEGORY_MARKETING: False}
    client_fatou.save(update_fields=["notification_preferences"])

    emit(MARKETING_EVENT, MARKETING_CONTEXT, tenant_a, [client_fatou, client_aicha])

    recipients = set(NotificationLog.objects.values_list("user", flat=True))
    assert recipients == {client_aicha.pk}


def test_refusing_a_never_opt_out_category_still_delivers(tenant_a, client_fatou):
    """
    Un code de connexion part malgré un refus enregistré.

    L'incohérence est tracée pour qu'on la corrige, mais elle ne doit pas
    enfermer l'utilisateur dehors.
    """
    make_templates_for_all_channels(OTP_EVENT)
    client_fatou.notification_preferences = {CATEGORY_OTP: False}
    client_fatou.save(update_fields=["notification_preferences"])

    result = emit(OTP_EVENT, OTP_CONTEXT, tenant_a, [client_fatou])

    assert result.logs_created > 0
    assert any(r.startswith("preference_violation:") for r in result.failure_reasons)
    trace = NotificationLog.objects.get(failure_reason__startswith="preference_violation:")
    assert trace.status == NotificationLog.Status.FAILED
    assert str(client_fatou.pk) in trace.failure_reason


@pytest.mark.parametrize(
    ("event_code", "context", "category"),
    [
        (OTP_EVENT, OTP_CONTEXT, CATEGORY_OTP),
        (
            "notif.auth.suspicious_activity.v1",
            {"ip": "10.0.0.1", "attempted_at": "2026-09-07T10:00:00+00:00"},
            CATEGORY_SECURITY,
        ),
        (
            "notif.trip.cancelled.v1",
            {
                "trip_code": "TRP-1", "route_label": "Dakar → Bamako",
                "reason": "Panne", "cancelled_at": "2026-09-07T10:00:00+00:00",
            },
            CATEGORY_CRITICAL_OPS,
        ),
    ],
)
def test_the_bypass_covers_every_never_opt_out_category(
    tenant_a, client_fatou, event_code, context, category,
):
    """La règle vaut pour les trois catégories, pas seulement pour les codes."""
    from django.utils import timezone

    assert category in NEVER_OPT_OUT
    make_templates_for_all_channels(event_code, template_body="{{ otp }}{{ trip_code }}")
    client_fatou.notification_preferences = {category: False}
    client_fatou.save(update_fields=["notification_preferences"])

    prepared = dict(context)
    for key, value in prepared.items():
        if key.endswith("_at") and isinstance(value, str):
            prepared[key] = timezone.now()

    result = emit(event_code, prepared, tenant_a, [client_fatou])

    assert result.logs_created > 0
    assert any(r.startswith(f"preference_violation:{category}") for r in result.failure_reasons)
