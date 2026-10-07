"""
TOUPAC Voyage — Verdict `duplicate` enrichi avec `original_status`.

Un rejeu d'un `client_uuid` déjà traité ne doit plus renvoyer un verdict
pauvre `{client_uuid, status: "duplicate"}` : le mobile a besoin du résultat
du premier traitement pour réconcilier son SQLite après timeout, sans
refetch de la ressource métier.

Cas couverts :
- Rejeu après `accepted` → `original_status: "accepted"`, pas de rejection_*
- Rejeu après `rejected` métier (ex. SEAT_ALREADY_TAKEN) → `original_status:
  "rejected"` + `rejection_code` et `rejection_reason` copiés
- Rejeu après rejet INTERNAL_ERROR (handler qui crashe) → `original_status:
  "rejected"` + `rejection_code: "INTERNAL_ERROR"`. **Valide la dette tracée
  en DETTES.md : un event piégé en INTERNAL_ERROR reste "duplicate à
  perpétuité" ; ce commit ne la résout pas, il la rend seulement visible.**
- Course concurrente simulée via `IntegrityError` → même format enrichi.
- Verdict non-duplicate (accepted / rejected nominal) : clé `original_status`
  **absente** du dict (préservation du contrat).
"""
import uuid
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from voyage.models import ControlEvent, Reservation
from voyage.services.event_processor import BatchEventProcessor
from voyage.services.exceptions import RejectionCode

# Réutilise les fixtures de test_batch_hardening (tenant, controller, trip,
# stops, session, processor, PASSENGER, sale_event, sell, existing_reservation).
from voyage.tests.test_batch_hardening import (  # noqa: F401
    PASSENGER,
    controller,
    processor,
    sale_event,
    sell,
    session,
    stops,
    tenant,
    trip,
    existing_reservation,
)

pytestmark = pytest.mark.django_db


def _replay(processor, verdict):
    """Rejoue un batch avec le même client_uuid que le verdict donné."""
    client_uuid = verdict["client_uuid"]
    stops_list = list(processor.session.trip.route.stops.order_by("stop_order"))
    event = sale_event(stops=stops_list)
    event["client_uuid"] = client_uuid
    return processor.process_batch([event])[0]


# ─── 1. Rejeu après accepted ───

def test_duplicate_verdict_after_accepted_carries_original_status(
    processor, trip,
):
    first = sell(processor)
    assert first["status"] == "accepted", first

    second = _replay(processor, first)
    assert second["status"] == "duplicate"
    assert second["original_status"] == "accepted"
    assert second["client_uuid"] == first["client_uuid"]
    # Pas de rejection_* parasites quand l'original a été accepté.
    assert "rejection_code" not in second
    assert "rejection_reason" not in second


# ─── 2. Rejeu après rejected métier ───

def test_duplicate_verdict_after_business_rejection_preserves_code_and_reason(
    processor, tenant, trip,
):
    # Occupe le siège A1 par une réservation existante, pour qu'une vente
    # à bord sur A1 soit rejetée en SEAT_ALREADY_TAKEN.
    existing_reservation(tenant, trip, "A1", Reservation.Status.BOOKED)

    first = sell(processor)
    assert first["status"] == "rejected", first
    assert first["rejection_code"] == RejectionCode.SEAT_ALREADY_TAKEN

    second = _replay(processor, first)
    assert second["status"] == "duplicate"
    assert second["original_status"] == "rejected"
    assert second["rejection_code"] == RejectionCode.SEAT_ALREADY_TAKEN
    assert second["rejection_reason"]  # non vide, copié depuis la ligne persistée


# ─── 3. Rejeu après INTERNAL_ERROR (dette documentée) ───

def test_duplicate_verdict_after_internal_error_remains_rejected(
    processor, trip,
):
    """
    Un handler qui crashe sur un `RuntimeError` tombe en INTERNAL_ERROR. Au
    rejeu du même client_uuid, le verdict duplicate transmet "rejected" +
    rejection_code INTERNAL_ERROR.

    DETTES.md : cet event est piégé — rejouer indéfiniment donnera toujours
    un verdict `duplicate` sans possibilité de retry côté serveur. Ce test
    rend simplement la dette visible côté mobile. La vraie résolution
    (requeue admin, retry policy côté serveur) est un chantier séparé.
    """
    import voyage.services.handlers.sales as sales_module

    original = sales_module.handle_onboard_sale

    def _boom(event, tenant_, session_):
        raise RuntimeError("provoque un INTERNAL_ERROR pour le test")

    sales_module.handle_onboard_sale = _boom
    try:
        from voyage.services.event_processor import EVENT_HANDLERS
        EVENT_HANDLERS["onboard_sale"] = _boom
        first = sell(processor)
    finally:
        sales_module.handle_onboard_sale = original
        from voyage.services.event_processor import EVENT_HANDLERS
        EVENT_HANDLERS["onboard_sale"] = original

    assert first["status"] == "rejected"
    assert first["rejection_code"] == RejectionCode.INTERNAL_ERROR

    second = _replay(processor, first)
    assert second["status"] == "duplicate"
    assert second["original_status"] == "rejected"
    assert second["rejection_code"] == RejectionCode.INTERNAL_ERROR
    assert "provoque un INTERNAL_ERROR" in second["rejection_reason"]


# ─── 4. Course concurrente (IntegrityError) ───

def test_duplicate_verdict_on_concurrent_race_also_enriches(
    processor, tenant, trip,
):
    """
    Simule une course entre deux batches sur le même client_uuid. Le second
    batch tombe sur un `IntegrityError` dans sa transaction atomique — le
    code doit relire l'event déjà persisté par le premier batch et renvoyer
    le même format enrichi (pas un verdict pauvre).
    """
    stops_list = list(trip.route.stops.order_by("stop_order"))
    event = sale_event(stops=stops_list)
    client_uuid = event["client_uuid"]

    # 1er batch : passe normalement.
    first = processor.process_batch([event])[0]
    assert first["status"] == "accepted"

    # 2e batch : on patch le filter du check d'idempotence pour qu'il ne
    # voie rien, forçant le code à atteindre le ControlEvent.create() qui
    # lèvera IntegrityError (contrainte unique sur tenant + client_uuid).
    original_filter = ControlEvent.objects.filter

    call_count = {"n": 0}

    class EmptyQS:
        def only(self, *args, **kwargs):
            return self
        def first(self):
            return None

    def _patched_filter(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1 and "client_uuid" in kwargs:
            return EmptyQS()
        return original_filter(**kwargs)

    with patch.object(ControlEvent.objects, "filter", side_effect=_patched_filter):
        second_event = dict(event)
        second_event["client_uuid"] = client_uuid
        second = processor.process_batch([second_event])[0]

    assert second["status"] == "duplicate"
    assert second["original_status"] == "accepted"
    assert "rejection_code" not in second


# ─── 5. Préservation du contrat non-duplicate ───

def test_accepted_verdict_does_not_leak_original_status(processor, trip):
    verdict = sell(processor)
    assert verdict["status"] == "accepted"
    assert "original_status" not in verdict


def test_rejected_verdict_does_not_leak_original_status(
    processor, tenant, trip,
):
    existing_reservation(tenant, trip, "A1", Reservation.Status.BOOKED)
    verdict = sell(processor)
    assert verdict["status"] == "rejected"
    assert "original_status" not in verdict
