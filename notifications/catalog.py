"""
Catalogue déclaratif des événements de notification TOUPAC ONE.

Source unique de vérité. Le service (Ticket B), les serializers (Ticket D),
le portail développeur, l'admin et les tests s'appuient tous sur ce fichier.
Toute évolution d'un événement (nouvelle variable, changement de priorité,
ajout de canal) passe par une nouvelle version : notif.foo.bar.v1 → v2.

Convention : notif.{domaine}.{evenement}.{version}

Le catalogue porte la PRIORITÉ, les CANAUX par défaut, la CATÉGORIE de
préférence, le RESOLVER de destinataires et les VARIABLES attendues. Les
`NotificationTemplate` en base ne portent que le RENDU (titre / corps / CTA)
par (event_code, channel, language, tenant).
"""
import datetime
import uuid
from dataclasses import dataclass, field
from typing import Any

from .channels import Channel
from .preferences import (
    ALL_CATEGORIES,
    CATEGORY_CRITICAL_OPS,
    CATEGORY_DISPATCH,
    CATEGORY_FLEET,
    CATEGORY_MARKETING,
    CATEGORY_OTP,
    CATEGORY_PARCEL_UPDATES,
    CATEGORY_PAYMENTS,
    CATEGORY_SECURITY,
    CATEGORY_TRIP_UPDATES,
    CATEGORY_WORKFLOW,
)
from .priorities import Priority

#: Types acceptés par `VariableSpec.type`. Un type inconnu casse à l'import.
SUPPORTED_TYPES = frozenset({"string", "int", "float", "datetime", "url", "uuid"})


@dataclass(frozen=True)
class VariableSpec:
    type: str
    required: bool = True
    max_length: int | None = None


@dataclass(frozen=True)
class NotifEvent:
    code: str                          # notif.payment.confirmed.v1
    charte_id: str                     # PAY-01 (traçabilité vers la charte)
    label: str                         # Libellé humain
    priority: Priority
    category: str                      # une clé de preferences.py (drive N-02)
    default_channels: tuple[Channel, ...]
    variables: dict[str, VariableSpec]
    resolver_key: str                  # clé du resolver enregistré
    requires_ack: bool = False
    action_buttons: tuple[str, ...] = field(default_factory=tuple)
    confidentiality_masks: tuple[str, ...] = field(default_factory=tuple)  # N-05


# ─── Registry ───

_EVENTS: dict[str, NotifEvent] = {}


def register(event: NotifEvent) -> None:
    """Enregistre un événement. Toute incohérence casse à l'import de l'app."""
    if event.code in _EVENTS:
        raise ValueError(f"Duplicate event code: {event.code}")
    if event.category not in ALL_CATEGORIES:
        raise ValueError(f"Unknown category '{event.category}' for {event.code}")
    if not event.default_channels:
        raise ValueError(f"{event.code}: at least one default channel required")
    for var_name, spec in event.variables.items():
        if spec.type not in SUPPORTED_TYPES:
            raise ValueError(f"{event.code}.{var_name}: unsupported type '{spec.type}'")
    # Un masque qui ne pointe sur aucune variable déclarée est une faute de
    # frappe silencieuse : le champ resterait en clair dans le push (N-05).
    for masked in event.confidentiality_masks:
        if masked not in event.variables:
            raise ValueError(f"{event.code}: confidentiality mask '{masked}' is not a declared variable")
    _EVENTS[event.code] = event


def get_event(code: str) -> NotifEvent:
    if code not in _EVENTS:
        raise KeyError(f"Unknown event code: {code}")
    return _EVENTS[code]


def all_events() -> list[NotifEvent]:
    return list(_EVENTS.values())


def events_by_family(prefix: str) -> list[NotifEvent]:
    """prefix = 'notif.payment' → tous les events paiement, toutes versions."""
    return [e for e in _EVENTS.values() if e.code.startswith(prefix + ".")]


def validate_context(event_code: str, context: dict[str, Any]) -> None:
    """Lève ValueError si le contexte ne respecte pas le schéma de l'événement.

    Permissif sur les clés en trop : le rendu d'un gabarit peut légitimement
    recevoir des variables d'agrément non déclarées. Strict sur les variables
    déclarées (présence, type, longueur).
    """
    event = get_event(event_code)
    for var_name, spec in event.variables.items():
        if var_name not in context:
            if spec.required:
                raise ValueError(f"{event_code}: missing required variable '{var_name}'")
            continue
        _check_type(event_code, var_name, context[var_name], spec)


def _check_type(event_code: str, var_name: str, value: Any, spec: VariableSpec) -> None:
    where = f"{event_code}.{var_name}"
    got = type(value).__name__

    if spec.type in ("string", "url"):
        if not isinstance(value, str):
            raise ValueError(f"{where}: expected string, got {got}")
        if spec.type == "url" and not value.startswith(("http://", "https://", "/")):
            raise ValueError(f"{where}: expected an http(s) or root-relative URL, got {value!r}")
    elif spec.type == "int":
        # bool est un sous-type d'int en Python : `amount_xof=True` passerait.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{where}: expected int, got {got}")
    elif spec.type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{where}: expected float, got {got}")
    elif spec.type == "datetime":
        if not isinstance(value, datetime.datetime):
            raise ValueError(f"{where}: expected datetime, got {got}")
    elif spec.type == "uuid":
        if isinstance(value, uuid.UUID):
            pass
        elif isinstance(value, str):
            try:
                uuid.UUID(value)
            except ValueError:
                raise ValueError(f"{where}: expected uuid, got {value!r}") from None
        else:
            raise ValueError(f"{where}: expected uuid, got {got}")

    if spec.max_length is not None and isinstance(value, str) and len(value) > spec.max_length:
        raise ValueError(f"{where}: exceeds max_length {spec.max_length}")


# ─── Déclarations des 37 événements TOUPAC ONE ───
#
# Les canaux listés sont TOUS les canaux possibles. Le conditionnel de la charte
# (« email si e-mail vérifié », « email si retard > 30 min », …) est appliqué au
# Ticket B par `default_channels_for(user)` — le catalogue ne tranche pas.

_S = VariableSpec  # alias local : 37 déclarations, la lisibilité y gagne


# ── AUTH — authentification et sécurité du compte ──

register(NotifEvent(
    code="notif.auth.otp_signin.v1",
    charte_id="AUTH-01",
    label="Code de connexion",
    priority=Priority.CRITICAL,
    category=CATEGORY_OTP,
    default_channels=(Channel.IN_APP, Channel.EMAIL, Channel.SMS, Channel.WHATSAPP),
    variables={
        "otp": _S(type="string", required=True, max_length=8),
        "expires_in_minutes": _S(type="int", required=True),
        "device_label": _S(type="string", required=False, max_length=120),
    },
    resolver_key="auth.self",
    confidentiality_masks=("otp",),
))

register(NotifEvent(
    code="notif.auth.otp_password_reset.v1",
    charte_id="AUTH-02",
    label="Code de réinitialisation du mot de passe",
    priority=Priority.CRITICAL,
    category=CATEGORY_OTP,
    default_channels=(Channel.IN_APP, Channel.EMAIL, Channel.SMS, Channel.WHATSAPP),
    variables={
        "otp": _S(type="string", required=True, max_length=8),
        "expires_in_minutes": _S(type="int", required=True),
    },
    resolver_key="auth.self",
    confidentiality_masks=("otp",),
))

register(NotifEvent(
    code="notif.auth.suspicious_activity.v1",
    charte_id="AUTH-03",
    label="Activité suspecte détectée",
    priority=Priority.CRITICAL,
    category=CATEGORY_SECURITY,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "ip": _S(type="string", required=True, max_length=45),
        "location": _S(type="string", required=False, max_length=120),
        "attempted_at": _S(type="datetime", required=True),
    },
    resolver_key="auth.self_and_admins",
    confidentiality_masks=("ip", "location"),
))


# ── CMD — commandes (voyage.Reservation ou colis.Order) ──
#
# `order_type` porte le type d'objet concret : "reservation" (billet voyage) ou
# "parcel" (commande colis). Le catalogue ne restreint pas les valeurs — string
# libre, validation stricte reportée au Ticket B.

register(NotifEvent(
    code="notif.order.confirmed.v1",
    charte_id="CMD-01",
    label="Commande confirmée",
    priority=Priority.HIGH,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "order_type": _S(type="string", required=True, max_length=20),
        "reference": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "departure_at": _S(type="datetime", required=True),
        "seat_label": _S(type="string", required=False, max_length=10),
    },
    resolver_key="order.customer",
))

register(NotifEvent(
    code="notif.order.expiring.v1",
    charte_id="CMD-02",
    label="Commande bientôt expirée",
    priority=Priority.MEDIUM,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "order_type": _S(type="string", required=True, max_length=20),
        "reference": _S(type="string", required=True, max_length=20),
        "expires_at": _S(type="datetime", required=True),
        "amount_xof": _S(type="int", required=True),
    },
    resolver_key="order.customer",
))

register(NotifEvent(
    code="notif.order.expired.v1",
    charte_id="CMD-03",
    label="Commande expirée",
    priority=Priority.MEDIUM,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "order_type": _S(type="string", required=True, max_length=20),
        "reference": _S(type="string", required=True, max_length=20),
        "expired_at": _S(type="datetime", required=True),
    },
    resolver_key="order.customer_and_agent",
))


# ── PAY — paiements ──

register(NotifEvent(
    code="notif.payment.confirmed.v1",
    charte_id="PAY-01",
    label="Paiement confirmé",
    priority=Priority.CRITICAL,
    category=CATEGORY_PAYMENTS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "reference": _S(type="string", required=True, max_length=20),
        "amount_xof": _S(type="int", required=True),
        "receipt_url": _S(type="url", required=False),
    },
    resolver_key="payment.customer",
    confidentiality_masks=("amount_xof",),  # N-05 : pas de montant en push
))

register(NotifEvent(
    code="notif.payment.failed.v1",
    charte_id="PAY-02",
    label="Paiement échoué",
    priority=Priority.HIGH,
    category=CATEGORY_PAYMENTS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "reference": _S(type="string", required=True, max_length=20),
        "amount_xof": _S(type="int", required=True),
        "failure_reason": _S(type="string", required=True, max_length=200),
    },
    resolver_key="payment.customer",
))

register(NotifEvent(
    code="notif.payment.refunded.v1",
    charte_id="PAY-03",
    label="Paiement remboursé",
    priority=Priority.HIGH,
    category=CATEGORY_PAYMENTS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "reference": _S(type="string", required=True, max_length=20),
        "amount_xof": _S(type="int", required=True),
        "refunded_at": _S(type="datetime", required=True),
    },
    resolver_key="payment.customer_and_finance",
    confidentiality_masks=("amount_xof",),
))


# ── TKT — billetterie ──

register(NotifEvent(
    code="notif.ticket.issued.v1",
    charte_id="TKT-01",
    label="Billet émis",
    priority=Priority.CRITICAL,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "reference": _S(type="string", required=True, max_length=20),
        "qr_payload": _S(type="string", required=True, max_length=500),
        "route_label": _S(type="string", required=True, max_length=120),
        "departure_at": _S(type="datetime", required=True),
    },
    resolver_key="ticket.customer",
    confidentiality_masks=("qr_payload",),
))


# ── TRJ — trajets ──

register(NotifEvent(
    code="notif.trip.reminder.v1",
    charte_id="TRJ-01",
    label="Rappel de départ",
    priority=Priority.MEDIUM,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "trip_code": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "departure_at": _S(type="datetime", required=True),
    },
    resolver_key="trip.customer_and_driver",
))

register(NotifEvent(
    code="notif.trip.updated.v1",
    charte_id="TRJ-02",
    label="Trajet modifié",
    priority=Priority.HIGH,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "trip_code": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "change_summary": _S(type="string", required=True, max_length=300),
        "departure_at": _S(type="datetime", required=True),
    },
    resolver_key="trip.all_stakeholders",
))

register(NotifEvent(
    code="notif.trip.delayed.v1",
    charte_id="TRJ-03",
    label="Trajet retardé",
    priority=Priority.HIGH,
    category=CATEGORY_TRIP_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "trip_code": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "delay_minutes": _S(type="int", required=True),
        "new_departure_at": _S(type="datetime", required=True),
    },
    resolver_key="trip.customer_and_station",
))

register(NotifEvent(
    code="notif.trip.cancelled.v1",
    charte_id="TRJ-04",
    label="Trajet annulé",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "trip_code": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "reason": _S(type="string", required=True, max_length=300),
        "cancelled_at": _S(type="datetime", required=True),
    },
    resolver_key="trip.all_stakeholders",
))


# ── DSP — dispatch (coordination Dispatcher ↔ Chauffeur, unidirectionnelle) ──

register(NotifEvent(
    code="notif.dispatch.assigned.v1",
    charte_id="DSP-01",
    label="Mission assignée",
    priority=Priority.CRITICAL,
    category=CATEGORY_DISPATCH,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "assignment_id": _S(type="uuid", required=True),
        "trip_code": _S(type="string", required=True, max_length=20),
        "route_label": _S(type="string", required=True, max_length=120),
        "departure_at": _S(type="datetime", required=True),
        "vehicle_label": _S(type="string", required=True, max_length=60),
    },
    resolver_key="dispatch.driver",
    requires_ack=True,
    action_buttons=("accept", "decline"),
))

register(NotifEvent(
    code="notif.dispatch.responded.v1",
    charte_id="DSP-02",
    label="Réponse du chauffeur",
    priority=Priority.HIGH,
    category=CATEGORY_DISPATCH,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "assignment_id": _S(type="uuid", required=True),
        "driver_name": _S(type="string", required=True, max_length=120),
        "response": _S(type="string", required=True, max_length=20),
        "responded_at": _S(type="datetime", required=True),
    },
    resolver_key="dispatch.dispatcher",
))

register(NotifEvent(
    code="notif.dispatch.conflict.v1",
    charte_id="DSP-03",
    label="Conflit d'affectation",
    priority=Priority.HIGH,
    category=CATEGORY_DISPATCH,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "assignment_id": _S(type="uuid", required=True),
        "conflict_summary": _S(type="string", required=True, max_length=300),
        "trip_code": _S(type="string", required=True, max_length=20),
    },
    resolver_key="dispatch.dispatcher",
))


# ── CTL — contrôle à bord ──

register(NotifEvent(
    code="notif.control.invalid_ticket.v1",
    charte_id="CTL-01",
    label="Billet invalide au contrôle",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "trip_code": _S(type="string", required=True, max_length=20),
        "passenger_id": _S(type="string", required=True, max_length=40),
        "reason": _S(type="string", required=True, max_length=200),
        "scanned_at": _S(type="datetime", required=True),
    },
    resolver_key="control.controller_and_supervisor",
    confidentiality_masks=("passenger_id",),
))


# ── COL — colis ──

register(NotifEvent(
    code="notif.parcel.registered.v1",
    charte_id="COL-01",
    label="Colis enregistré",
    priority=Priority.HIGH,
    category=CATEGORY_PARCEL_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "origin_label": _S(type="string", required=True, max_length=120),
        "destination_label": _S(type="string", required=True, max_length=120),
    },
    resolver_key="parcel.sender_and_recipient",
))

register(NotifEvent(
    code="notif.parcel.picked_up.v1",
    charte_id="COL-02",
    label="Colis pris en charge",
    priority=Priority.HIGH,
    category=CATEGORY_PARCEL_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "picked_up_at": _S(type="datetime", required=True),
    },
    resolver_key="parcel.sender",
))

register(NotifEvent(
    code="notif.parcel.eta_updated.v1",
    charte_id="COL-03",
    label="Estimation de livraison mise à jour",
    priority=Priority.MEDIUM,
    category=CATEGORY_PARCEL_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "eta_at": _S(type="datetime", required=True),
    },
    resolver_key="parcel.recipient",
))

register(NotifEvent(
    code="notif.parcel.ready_pickup.v1",
    charte_id="COL-04",
    label="Colis disponible au retrait",
    priority=Priority.HIGH,
    category=CATEGORY_PARCEL_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "pickup_point": _S(type="string", required=True, max_length=120),
        "available_until": _S(type="datetime", required=False),
    },
    resolver_key="parcel.recipient",
))

register(NotifEvent(
    code="notif.parcel.pickup_otp.v1",
    charte_id="COL-05",
    label="Code de retrait du colis",
    priority=Priority.CRITICAL,
    category=CATEGORY_OTP,
    default_channels=(Channel.IN_APP, Channel.SMS, Channel.WHATSAPP),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "otp": _S(type="string", required=True, max_length=8),
        "expires_in_minutes": _S(type="int", required=True),
    },
    resolver_key="parcel.recipient",
    confidentiality_masks=("otp",),
))

register(NotifEvent(
    code="notif.parcel.delivered.v1",
    charte_id="COL-06",
    label="Colis livré",
    priority=Priority.CRITICAL,
    category=CATEGORY_PARCEL_UPDATES,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "tracking_number": _S(type="string", required=True, max_length=30),
        "recipient_name": _S(type="string", required=True, max_length=120),
        "delivered_at": _S(type="datetime", required=True),
        "signature_url": _S(type="url", required=False),
    },
    resolver_key="parcel.sender",
    confidentiality_masks=("signature_url",),
))


# ── INC — incidents d'exploitation ──

register(NotifEvent(
    code="notif.incident.opened.v1",
    charte_id="INC-01",
    label="Incident ouvert",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "incident_id": _S(type="uuid", required=True),
        "severity": _S(type="string", required=True, max_length=20),
        "summary": _S(type="string", required=True, max_length=300),
        "trip_code": _S(type="string", required=False, max_length=20),
    },
    resolver_key="incident.dispatchers_and_admin",
))

register(NotifEvent(
    code="notif.incident.resolved.v1",
    charte_id="INC-02",
    label="Incident résolu",
    priority=Priority.HIGH,
    # Symétrique de INC-01 (critical_ops) : un client qui coupe trip_updates ne
    # doit pas rater la résolution d'un incident qui l'a impacté.
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "incident_id": _S(type="uuid", required=True),
        "summary": _S(type="string", required=True, max_length=300),
        "resolved_at": _S(type="datetime", required=True),
        "internal_notes": _S(type="string", required=False, max_length=500),
    },
    resolver_key="incident.reporter_and_impacted",
    confidentiality_masks=("internal_notes",),
))


# ── GPS — télématique ──

register(NotifEvent(
    code="notif.gps.alert.v1",
    charte_id="GPS-01",
    label="Alerte GPS",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "vehicle_label": _S(type="string", required=True, max_length=60),
        "alert_type": _S(type="string", required=True, max_length=40),
        "detected_at": _S(type="datetime", required=True),
        "location": _S(type="string", required=False, max_length=120),
    },
    resolver_key="gps.dispatchers_and_fleet",
    requires_ack=True,
    action_buttons=("acknowledge",),
))

register(NotifEvent(
    code="notif.gps.vehicle_offline.v1",
    charte_id="GPS-02",
    label="Véhicule hors ligne",
    priority=Priority.HIGH,
    category=CATEGORY_FLEET,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "vehicle_label": _S(type="string", required=True, max_length=60),
        "last_seen_at": _S(type="datetime", required=True),
        "offline_minutes": _S(type="int", required=True),
    },
    resolver_key="gps.dispatchers_and_it",
))


# ── FLT — flotte ──

register(NotifEvent(
    code="notif.fleet.maintenance_due.v1",
    charte_id="FLT-01",
    label="Maintenance à échéance",
    priority=Priority.HIGH,
    category=CATEGORY_FLEET,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "vehicle_label": _S(type="string", required=True, max_length=60),
        "maintenance_type": _S(type="string", required=True, max_length=60),
        "due_at": _S(type="datetime", required=True),
        "odometer_km": _S(type="int", required=False),
    },
    resolver_key="fleet.manager_and_mechanic",
))


# ── CMP — conformité documentaire ──

register(NotifEvent(
    code="notif.compliance.document_expiring.v1",
    charte_id="CMP-01",
    label="Document réglementaire bientôt expiré",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "document_type": _S(type="string", required=True, max_length=60),
        "holder_label": _S(type="string", required=True, max_length=120),
        "expires_at": _S(type="datetime", required=True),
        "days_left": _S(type="int", required=True),
    },
    resolver_key="compliance.responsible_and_driver",
))


# ── FIN — finance ──

register(NotifEvent(
    code="notif.finance.cash_discrepancy.v1",
    charte_id="FIN-01",
    label="Écart de caisse",
    priority=Priority.CRITICAL,
    category=CATEGORY_CRITICAL_OPS,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "station_label": _S(type="string", required=True, max_length=120),
        "amount_xof": _S(type="int", required=True),
        "details": _S(type="string", required=True, max_length=300),
        "detected_at": _S(type="datetime", required=True),
    },
    resolver_key="finance.finance_and_station",
    confidentiality_masks=("amount_xof", "details"),
))


# ── APR / STK / CRM / BI — workflow transverse ──

register(NotifEvent(
    code="notif.approval.pending.v1",
    charte_id="APR-01",
    label="Validation en attente",
    priority=Priority.MEDIUM,
    category=CATEGORY_WORKFLOW,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "request_id": _S(type="uuid", required=True),
        "request_type": _S(type="string", required=True, max_length=60),
        "requester_name": _S(type="string", required=True, max_length=120),
        "submitted_at": _S(type="datetime", required=True),
    },
    resolver_key="approval.approver",
))

register(NotifEvent(
    code="notif.stock.low.v1",
    charte_id="STK-01",
    label="Stock bas",
    priority=Priority.HIGH,
    category=CATEGORY_WORKFLOW,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "item_label": _S(type="string", required=True, max_length=120),
        "remaining_qty": _S(type="int", required=True),
        "threshold_qty": _S(type="int", required=True),
        "warehouse_label": _S(type="string", required=True, max_length=120),
    },
    resolver_key="stock.warehouse_and_purchase",
))

register(NotifEvent(
    code="notif.crm.complaint_updated.v1",
    charte_id="CRM-01",
    label="Réclamation mise à jour",
    priority=Priority.HIGH,
    category=CATEGORY_WORKFLOW,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "complaint_id": _S(type="uuid", required=True),
        "status": _S(type="string", required=True, max_length=40),
        "summary": _S(type="string", required=True, max_length=300),
        "internal_notes": _S(type="string", required=False, max_length=500),
    },
    resolver_key="crm.customer_and_agent",
    confidentiality_masks=("internal_notes",),
))

register(NotifEvent(
    code="notif.bi.report_ready.v1",
    charte_id="BI-01",
    label="Rapport disponible",
    priority=Priority.MEDIUM,
    category=CATEGORY_WORKFLOW,
    default_channels=(Channel.IN_APP, Channel.EMAIL),
    variables={
        "report_label": _S(type="string", required=True, max_length=120),
        "period_label": _S(type="string", required=True, max_length=60),
        "report_url": _S(type="url", required=True),
    },
    resolver_key="bi.direction_and_finance",
))


# ── MKT — marketing (seule famille réellement opt-out) ──

register(NotifEvent(
    code="notif.marketing.promo.v1",
    charte_id="MKT-01",
    label="Offre promotionnelle",
    priority=Priority.LOW,
    category=CATEGORY_MARKETING,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "campaign_label": _S(type="string", required=True, max_length=120),
        "promo_code": _S(type="string", required=False, max_length=30),
        "valid_until": _S(type="datetime", required=False),
        "landing_url": _S(type="url", required=False),
    },
    resolver_key="marketing.consented_customers",
))


# ── SI — incidents plateforme ──

register(NotifEvent(
    code="notif.platform.system_incident.v1",
    charte_id="SI-01",
    label="Incident système",
    priority=Priority.CRITICAL,
    category=CATEGORY_SECURITY,
    default_channels=(Channel.PUSH, Channel.IN_APP, Channel.EMAIL),
    variables={
        "incident_id": _S(type="uuid", required=True),
        "component": _S(type="string", required=True, max_length=60),
        "severity": _S(type="string", required=True, max_length=20),
        "summary": _S(type="string", required=True, max_length=300),
    },
    resolver_key="si.admins_and_support",
))
