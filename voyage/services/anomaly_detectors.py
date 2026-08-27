"""
TOUPAC Voyage — Détecteurs d'anomalies automatiques.

Appelés par les handlers d'events offline pour repérer les incohérences que
l'app mobile ne peut pas détecter seule (elle n'a qu'une vue partielle et
potentiellement périmée du voyage).
"""
from django.db.models import Q

from voyage.models import Anomaly, ControlEvent, Reservation


def serialize_anomaly(anomaly):
    """Représentation compacte d'une anomalie, renvoyée dans le verdict d'un event."""
    if anomaly is None:
        return None
    return {
        "id": str(anomaly.id),
        "type": anomaly.type,
        "severity": anomaly.severity,
        "title": anomaly.title,
        "description": anomaly.description,
    }


def detect_duplicate_scan(tenant, reservation_id, session, event=None):
    """
    Détecte un billet scanné deux fois.

    Deux signaux : la réservation est déjà au statut `boarded`, ou un précédent
    event `reservation_board` non rejeté cible déjà cette réservation. Doit être
    appelé AVANT la mutation de la réservation, sinon le premier signal est
    toujours vrai.

    Retourne l'Anomaly créée, ou None si aucun doublon.
    """
    reservation = Reservation.objects.filter(tenant=tenant, id=reservation_id).first()
    if reservation is None:
        return None

    already_boarded = reservation.status == Reservation.Status.BOARDED

    prior_scans = ControlEvent.objects.filter(
        Q(target_id=reservation_id) | Q(payload__reservation_id=str(reservation_id)),
        tenant=tenant,
        event_type="reservation_board",
    ).exclude(status=ControlEvent.Status.REJECTED)
    if event is not None:
        prior_scans = prior_scans.exclude(pk=event.pk)

    if not already_boarded and not prior_scans.exists():
        return None

    return Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=Anomaly.Type.DUPLICATE_SCAN,
        severity=Anomaly.Severity.MODERATE,
        title=f"Scan en double — siège {reservation.seat_label}",
        description=(
            f"Le billet {reservation.id} (passager {reservation.passenger_id}, "
            f"siège {reservation.seat_label}) a déjà été scanné. "
            f"Statut courant : {reservation.status}."
        ),
        target_type="reservation",
        target_id=reservation.id,
    )


def detect_seat_conflict(tenant, trip, seat_label, current_reservation_id, session=None, event=None):
    """
    Détecte deux passagers embarqués sur le même siège d'un voyage.

    Retourne l'Anomaly créée, ou None si aucun conflit.
    """
    conflicting = (
        Reservation.objects.filter(
            tenant=tenant,
            trip=trip,
            seat_label=seat_label,
            status=Reservation.Status.BOARDED,
        )
        .exclude(id=current_reservation_id)
        .select_related("passenger")
        .first()
    )
    if conflicting is None:
        return None

    return Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=Anomaly.Type.SEAT_CONFLICT,
        severity=Anomaly.Severity.CRITICAL,
        title=f"Conflit de siège {seat_label} — {trip.internal_id}",
        description=(
            f"Le siège {seat_label} du voyage {trip.internal_id} est occupé par "
            f"deux passagers embarqués : réservations {conflicting.id} et "
            f"{current_reservation_id}."
        ),
        target_type="reservation",
        target_id=current_reservation_id,
    )
