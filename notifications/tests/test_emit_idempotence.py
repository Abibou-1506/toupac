"""
TOUPAC Notifications — Idempotence (N-06), aux deux étages.

Redis évite le travail quand une émission se répète ; la contrainte unique en
base tranche la course que Redis ne peut pas arbitrer. Les deux sont testés
séparément, parce qu'ils ne protègent pas du même problème.
"""
from unittest import mock

import pytest
from django.db import IntegrityError

from notifications.catalog import get_event
from notifications.idempotency import compute_idempotency_key
from notifications.models import Notification, NotificationLog
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_templates_for_all_channels,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db

TICKET_RESOLVER = get_event(TICKET_EVENT).resolver_key


def emit(tenant, recipients, context=None, **kwargs):
    with temporary_resolver(TICKET_RESOLVER, resolver_returning(*recipients)):
        return NotificationService.emit(
            event_code=TICKET_EVENT, context=context or ticket_context(),
            tenant=tenant, **kwargs,
        )


# ─── Étage Redis ───

def test_second_identical_emit_is_a_hit(tenant_a, client_fatou):
    make_templates_for_all_channels()
    context = ticket_context()

    first = emit(tenant_a, [client_fatou], context)
    second = emit(tenant_a, [client_fatou], context)

    assert first.idempotency_hit is False
    assert second.idempotency_hit is True
    assert second.logs_created == 0
    assert Notification.objects.count() == 1


def test_different_actors_are_not_deduplicated(tenant_a, client_fatou, user_admin_a, user_dispatcher_a):
    """Deux personnes déclenchant le même événement produisent deux émissions."""
    make_templates_for_all_channels()
    context = ticket_context()

    first = emit(tenant_a, [client_fatou], context, actor=user_admin_a)
    second = emit(tenant_a, [client_fatou], context, actor=user_dispatcher_a)

    assert first.idempotency_hit is False
    assert second.idempotency_hit is False


def test_different_context_is_not_deduplicated(tenant_a, client_fatou):
    make_templates_for_all_channels()

    first = emit(tenant_a, [client_fatou], ticket_context(reference="REF-001"))
    second = emit(tenant_a, [client_fatou], ticket_context(reference="REF-002"))

    assert first.idempotency_hit is False
    assert second.idempotency_hit is False


def test_an_explicit_scope_separates_two_identical_emissions(tenant_a, client_fatou):
    """Deux rappels du même voyage ont le même contexte — le scope les sépare."""
    make_templates_for_all_channels()
    context = ticket_context()

    first = emit(tenant_a, [client_fatou], context, idempotency_scope="rappel-j-2")
    second = emit(tenant_a, [client_fatou], context, idempotency_scope="rappel-j-1")

    assert first.idempotency_hit is False
    assert second.idempotency_hit is False


def test_a_fully_failed_emission_does_not_block_a_retry(tenant_a, client_fatou):
    """
    Si rien n'est parti, l'appelant doit pouvoir retenter tout de suite.

    Poser la marque sur un échec total condamnerait l'événement pour la journée.
    """
    # Aucun gabarit créé : tous les canaux échouent.
    first = emit(tenant_a, [client_fatou])
    assert first.logs_created == 0
    assert first.logs_failed > 0

    make_templates_for_all_channels()
    second = emit(tenant_a, [client_fatou])

    assert second.idempotency_hit is False
    assert second.logs_created > 0


# ─── Clé de calcul ───

def test_key_is_stable_across_dict_ordering():
    """Deux contextes équivalents mais construits différemment ont la même clé."""
    first = compute_idempotency_key("e", context={"a": 1, "b": 2})
    second = compute_idempotency_key("e", context={"b": 2, "a": 1})

    assert first == second


def test_key_handles_values_json_cannot_serialise():
    """Dates et UUID passent par leur représentation textuelle plutôt que d'échouer."""
    import uuid
    from datetime import datetime

    key = compute_idempotency_key(
        "e", context={"quand": datetime(2026, 9, 7, 12, 0), "quoi": uuid.uuid4()},
    )

    assert len(key) == 32


def test_key_fits_the_database_column():
    """La colonne `Notification.idempotency_key` est dimensionnée à 100."""
    field = Notification._meta.get_field("idempotency_key")

    assert len(compute_idempotency_key("e", context={})) <= field.max_length


# ─── Étage base de données ───

def test_a_race_between_workers_does_not_raise(tenant_a, client_fatou):
    """
    Deux workers entrés dans la même fenêtre : la base tranche, sans erreur métier.

    Redis ne sérialise pas — entre le `get` et le `set`, l'autre worker est déjà
    passé. La contrainte unique attrape ce que le cache laisse filer, et le
    perdant récupère l'item du gagnant.
    """
    make_templates_for_all_channels()
    context = ticket_context()
    key = compute_idempotency_key(TICKET_EVENT, actor_id=None, scope=None, context=context)

    # L'item existe déjà : c'est l'état que le worker « perdant » va rencontrer.
    existing = Notification.objects.create(
        tenant=tenant_a, event_code=TICKET_EVENT, recipient_user=client_fatou,
        trigger_scope=Notification.TriggerScope.USER,
        priority=get_event(TICKET_EVENT).priority.value,
        title="Déjà là", body="Déjà là", idempotency_key=key,
    )

    result = emit(tenant_a, [client_fatou], context)

    # Aucun doublon créé, et l'émission a poursuivi ses canaux normalement.
    assert Notification.objects.count() == 1
    assert result.notifications_created == 0
    assert result.logs_created > 0
    assert NotificationLog.objects.filter(notification=existing).exists()


def test_an_unexplained_integrity_error_is_not_swallowed(tenant_a, client_fatou):
    """
    Une violation qui n'est pas une course doit remonter.

    Traiter toute `IntegrityError` comme un doublon masquerait un vrai défaut de
    schéma — le service ne récupère que s'il retrouve effectivement l'item.
    """
    make_templates_for_all_channels()

    with (
        temporary_resolver(TICKET_RESOLVER, resolver_returning(client_fatou)),
        mock.patch.object(
            Notification.objects, "create", side_effect=IntegrityError("colonne inattendue"),
        ),
        pytest.raises(IntegrityError),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(), tenant=tenant_a,
        )
