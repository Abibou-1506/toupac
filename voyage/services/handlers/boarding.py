"""TOUPAC Voyage — Handlers d'embarquement (board / refuse / special case)."""
from django.db.models import F

from voyage.models import Anomaly, Reservation, Trip
from voyage.services.anomaly_detectors import (
    detect_duplicate_scan, detect_seat_conflict, serialize_anomaly,
)
from voyage.services.exceptions import EventRejected


def _load_reservation(event, tenant):
    """Résout la réservation ciblée par l'event (payload prioritaire, puis target_id)."""
    reservation_id = event.payload.get("reservation_id") or event.target_id
    if not reservation_id:
        raise EventRejected("reservation_id manquant dans le payload.")
    reservation = (
        Reservation.objects.select_related("passenger", "trip")
        .filter(tenant=tenant, id=reservation_id)
        .first()
    )
    if reservation is None:
        raise EventRejected(f"Réservation {reservation_id} introuvable.")
    return reservation


def handle_board(event, tenant, session):
    """Embarque un passager après scan de son billet."""
    reservation = _load_reservation(event, tenant)

    # Détecté avant la mutation : après, le statut `boarded` serait toujours vrai.
    anomaly = detect_duplicate_scan(tenant, reservation.id, session, event=event)

    if reservation.status not in (Reservation.Status.BOOKED, Reservation.Status.CHECKED_IN):
        # Rejet « propre » : on garde l'anomalie qui documente le doublon.
        return {
            "status": "rejected",
            "rejection_reason": f"Embarquement impossible : statut={reservation.status}",
            "anomaly": serialize_anomaly(anomaly),
        }

    reservation.status = Reservation.Status.BOARDED
    reservation.boarded_at = event.created_at_local
    reservation.boarding_method = event.payload.get("boarding_method", "qr_scan")
    update_fields = ["status", "boarded_at", "boarding_method", "updated_at"]

    controller_id = event.payload.get("boarded_by_controller_id")
    if controller_id:
        reservation.boarded_by_id = controller_id
        update_fields.append("boarded_by")
    reservation.save(update_fields=update_fields)

    trip = reservation.trip
    Trip.objects.filter(pk=trip.pk).update(booked_seats=F("booked_seats") + 1)
    if trip.status == Trip.Status.PREPARING:
        trip.status = Trip.Status.BOARDING
        trip.save(update_fields=["status", "updated_at"])

    if anomaly is None:
        anomaly = detect_seat_conflict(
            tenant, trip, reservation.seat_label, reservation.id,
            session=session, event=event,
        )

    return {
        "status": "accepted",
        "anomaly": serialize_anomaly(anomaly),
        "reservation_id": str(reservation.id),
        "trip_status": trip.status,
    }


def handle_refuse(event, tenant, session):
    """Refuse l'embarquement d'un passager — génère systématiquement une anomalie."""
    reservation = _load_reservation(event, tenant)
    reason = event.payload.get("reason", "")

    reservation.status = Reservation.Status.REFUSED
    reservation.refusal_reason = reason[:200]
    reservation.save(update_fields=["status", "refusal_reason", "updated_at"])

    anomaly = Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=Anomaly.Type.OTHER,
        severity=Anomaly.Severity.MODERATE,
        title="Refus embarquement",
        description=(
            f"Embarquement refusé pour la réservation {reservation.id} "
            f"(siège {reservation.seat_label}). Motif : {reason or 'non précisé'}."
        ),
        target_type="reservation",
        target_id=reservation.id,
    )

    return {
        "status": "accepted",
        "anomaly": serialize_anomaly(anomaly),
        "reservation_id": str(reservation.id),
    }


def handle_special_case(event, tenant, session):
    """Embarquement manuel hors procédure normale (billet illisible, litige résolu...)."""
    reservation = _load_reservation(event, tenant)

    reservation.status = Reservation.Status.BOARDED
    reservation.boarded_at = event.created_at_local
    reservation.boarding_method = "manual"
    reservation.special_case_reason = event.payload.get("reason", "")[:200]
    reservation.save(update_fields=[
        "status", "boarded_at", "boarding_method", "special_case_reason", "updated_at",
    ])

    return {
        "status": "accepted",
        "anomaly": None,
        "reservation_id": str(reservation.id),
    }
