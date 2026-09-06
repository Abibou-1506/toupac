"""TOUPAC Notifications — Invariants du catalogue des 37 événements (Ticket A).

Aucun accès base : le catalogue est du code pur, ces tests doivent rester
exécutables sans DB pour rester utilisables comme garde-fou d'import.
"""
import datetime

import pytest

from notifications.catalog import (
    SUPPORTED_TYPES,
    NotifEvent,
    VariableSpec,
    all_events,
    events_by_family,
    get_event,
    validate_context,
)
from notifications.channels import Channel
from notifications.models import NotificationTemplate
from notifications.preferences import ALL_CATEGORIES

VALID_PAYMENT_CONTEXT = {"reference": "REF-001", "amount_xof": 15000}


# ─── Complétude et unicité ───

def test_all_37_events_registered():
    assert len(all_events()) == 37


def test_all_event_codes_are_unique():
    codes = [e.code for e in all_events()]
    assert len(codes) == len(set(codes))


def test_all_charte_ids_are_unique():
    charte_ids = [e.charte_id for e in all_events()]
    assert len(charte_ids) == len(set(charte_ids))


def test_all_categories_are_valid():
    for event in all_events():
        assert event.category in ALL_CATEGORIES, f"{event.code} porte une catégorie inconnue"


def test_all_event_codes_follow_naming_convention():
    """notif.{domaine}.{evenement}.{version} — 4 segments, versionnés vN."""
    for event in all_events():
        parts = event.code.split(".")
        assert len(parts) == 4, f"{event.code} n'a pas 4 segments"
        assert parts[0] == "notif", f"{event.code} ne commence pas par 'notif'"
        assert parts[3].startswith("v") and parts[3][1:].isdigit(), f"{event.code} mal versionné"


def test_all_variable_types_are_supported():
    for event in all_events():
        for name, spec in event.variables.items():
            assert spec.type in SUPPORTED_TYPES, f"{event.code}.{name}: type {spec.type!r}"


def test_confidentiality_masks_reference_declared_variables():
    """Un masque N-05 qui pointe dans le vide laisserait la donnée en clair en push."""
    for event in all_events():
        for masked in event.confidentiality_masks:
            assert masked in event.variables, f"{event.code}: masque '{masked}' non déclaré"


def test_events_requiring_ack_expose_action_buttons():
    """requires_ack sans bouton = accusé de réception impossible à donner."""
    for event in all_events():
        if event.requires_ack:
            assert event.action_buttons, f"{event.code} exige un ack sans bouton d'action"


def test_sms_and_whatsapp_are_reserved_to_otp_events():
    """Décision produit du 2 sept 2026 : SMS et WhatsApp sont strictement OTP-only.

    Encodée ici pour qu'un futur ajout d'événement ne la contourne pas en
    silence — c'est une contrainte de coût et de conformité, pas une préférence.
    """
    for event in all_events():
        narrow = {Channel.SMS, Channel.WHATSAPP} & set(event.default_channels)
        if narrow:
            assert event.category == "otp", (
                f"{event.code} ({event.category}) déclare {sorted(narrow)} hors contexte OTP"
            )


def test_catalog_channels_match_model_choices():
    """Le doublon enum/modèle est assumé — il ne doit jamais diverger."""
    assert {c.value for c in Channel} == {c for c, _ in NotificationTemplate.Channel.choices}


# ─── Familles ───

def test_events_by_family_returns_only_payment_events():
    family = events_by_family("notif.payment")
    assert {e.code for e in family} == {
        "notif.payment.confirmed.v1",
        "notif.payment.failed.v1",
        "notif.payment.refunded.v1",
    }


def test_events_by_family_does_not_match_on_partial_segment():
    """'notif.pay' ne doit pas ramener les events 'notif.payment.*'."""
    assert events_by_family("notif.pay") == []


def test_get_event_raises_on_unknown_code():
    with pytest.raises(KeyError, match="Unknown event code"):
        get_event("notif.nope.nope.v1")


# ─── validate_context ───

def test_validate_context_accepts_conforming_context():
    validate_context("notif.payment.confirmed.v1", VALID_PAYMENT_CONTEXT)


def test_validate_context_missing_required_variable():
    with pytest.raises(ValueError, match="missing required variable 'reference'"):
        validate_context("notif.payment.confirmed.v1", {"amount_xof": 15000})


def test_validate_context_wrong_type():
    context = VALID_PAYMENT_CONTEXT | {"amount_xof": "15000"}
    with pytest.raises(ValueError, match="expected int"):
        validate_context("notif.payment.confirmed.v1", context)


def test_validate_context_rejects_bool_for_int():
    """bool est un sous-type d'int : sans garde explicite, True passerait pour un montant."""
    context = VALID_PAYMENT_CONTEXT | {"amount_xof": True}
    with pytest.raises(ValueError, match="expected int"):
        validate_context("notif.payment.confirmed.v1", context)


def test_validate_context_max_length_exceeded():
    context = VALID_PAYMENT_CONTEXT | {"reference": "A" * 50}
    with pytest.raises(ValueError, match="exceeds max_length 20"):
        validate_context("notif.payment.confirmed.v1", context)


def test_validate_context_ignores_absent_optional_variable():
    validate_context("notif.payment.confirmed.v1", VALID_PAYMENT_CONTEXT)  # receipt_url absent


def test_validate_context_validates_optional_variable_when_present():
    context = VALID_PAYMENT_CONTEXT | {"receipt_url": "ftp://nope"}
    with pytest.raises(ValueError, match="http"):
        validate_context("notif.payment.confirmed.v1", context)


def test_validate_context_accepts_extra_undeclared_keys():
    """Le rendu peut recevoir des variables d'agrément — permissif par choix."""
    validate_context("notif.payment.confirmed.v1", VALID_PAYMENT_CONTEXT | {"nom": "Awa"})


def test_validate_context_checks_datetime_type():
    context = {
        "trip_code": "TRP-1", "route_label": "Dakar → Bamako",
        "change_summary": "Départ avancé", "departure_at": "2026-09-10",
    }
    with pytest.raises(ValueError, match="expected datetime"):
        validate_context("notif.trip.updated.v1", context)

    context["departure_at"] = datetime.datetime(2026, 9, 10, 8, 0)
    validate_context("notif.trip.updated.v1", context)


def test_validate_context_accepts_uuid_as_string_or_object():
    import uuid

    base = {
        "incident_id": uuid.uuid4(), "severity": "high", "summary": "Panne moteur",
    }
    validate_context("notif.incident.opened.v1", base)
    validate_context("notif.incident.opened.v1", base | {"incident_id": str(uuid.uuid4())})
    with pytest.raises(ValueError, match="expected uuid"):
        validate_context("notif.incident.opened.v1", base | {"incident_id": "pas-un-uuid"})


# ─── Garde-fous de `register` ───

def test_register_rejects_mask_on_undeclared_variable():
    """La validation tourne à l'import : une faute de frappe casse au démarrage."""
    from notifications.catalog import register

    with pytest.raises(ValueError, match="confidentiality mask"):
        register(NotifEvent(
            code="notif.test.bad_mask.v1", charte_id="TEST-99", label="Test",
            priority=next(iter(all_events())).priority, category="marketing",
            default_channels=(Channel.IN_APP,),
            variables={"foo": VariableSpec(type="string")},
            resolver_key="_example.customer_from_context",
            confidentiality_masks=("bar",),
        ))
