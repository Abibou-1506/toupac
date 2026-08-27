"""TOUPAC Voyage — Handler de vente à bord (billet émis par le contrôleur)."""
from django.db.models import F

from voyage.models import CashEntry, Passenger, Reservation, Trip
from voyage.services.exceptions import EventRejected


def handle_onboard_sale(event, tenant, session):
    """
    Vend un billet à bord : crée (ou réutilise) le passager, la réservation
    déjà embarquée, et l'encaissement correspondant.
    """
    payload = event.payload
    passenger_data = payload.get("passenger_data") or payload.get("passenger") or {}
    seat_label = payload.get("seat_label")
    amount_xof = payload.get("amount_xof")

    if not seat_label:
        raise EventRejected("seat_label manquant dans le payload.")
    if amount_xof is None:
        raise EventRejected("amount_xof manquant dans le payload.")

    trip_id = payload.get("trip_id")
    if trip_id:
        trip = Trip.objects.filter(tenant=tenant, id=trip_id).first()
        if trip is None:
            raise EventRejected(f"Voyage {trip_id} introuvable.")
    else:
        trip = session.trip

    # Réutilise le passager si son téléphone est déjà connu du tenant.
    phone = (passenger_data.get("phone") or "").strip()
    passenger = None
    if phone:
        passenger = Passenger.objects.filter(
            tenant=tenant, phone=phone, deleted_at__isnull=True,
        ).first()
    if passenger is None:
        passenger = Passenger.objects.create(
            tenant=tenant,
            first_name=passenger_data.get("first_name", ""),
            last_name=passenger_data.get("last_name", ""),
            phone=phone,
        )

    reservation = Reservation.objects.create(
        tenant=tenant,
        trip=trip,
        passenger=passenger,
        seat_label=seat_label,
        status=Reservation.Status.BOARDED,
        amount_xof=amount_xof,
        payment_method="onboard_cash",
        sales_channel="onboard",
        boarded_at=event.created_at_local,
        boarding_method="manual",
        boarded_by=session.controller,
    )

    cash_entry = CashEntry.objects.create(
        tenant=tenant,
        session=session,
        reservation=reservation,
        amount_xof=amount_xof,
        reason=CashEntry.Reason.ONBOARD_SALE,
        collected_by=session.controller,
    )

    Trip.objects.filter(pk=trip.pk).update(booked_seats=F("booked_seats") + 1)

    return {
        "status": "accepted",
        "anomaly": None,
        "passenger_id": str(passenger.id),
        "reservation_id": str(reservation.id),
        "cash_entry_id": str(cash_entry.id),
    }
