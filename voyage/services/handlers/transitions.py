"""TOUPAC Voyage — Handler de transition d'état d'un voyage depuis le terrain."""
from voyage.models import Trip
from voyage.services.exceptions import EventRejected

# Graphe des transitions autorisées sur un Trip (cf. Architecture §3.3).
# `cancelled` est atteignable depuis tout état non terminal ; le cycle
# in_transit ↔ at_stop couvre les escales multiples.
ALLOWED_TRANSITIONS = {
    Trip.Status.SCHEDULED: {Trip.Status.PREPARING, Trip.Status.CANCELLED},
    Trip.Status.PREPARING: {Trip.Status.BOARDING, Trip.Status.CANCELLED},
    Trip.Status.BOARDING: {Trip.Status.IN_TRANSIT, Trip.Status.CANCELLED},
    Trip.Status.IN_TRANSIT: {Trip.Status.AT_STOP, Trip.Status.CANCELLED},
    Trip.Status.AT_STOP: {Trip.Status.IN_TRANSIT, Trip.Status.ARRIVING, Trip.Status.CANCELLED},
    Trip.Status.ARRIVING: {Trip.Status.COMPLETED, Trip.Status.CANCELLED},
    Trip.Status.COMPLETED: set(),
    Trip.Status.CANCELLED: set(),
}


def handle_activity_transition(event, tenant, session):
    """Applique une transition d'état sur un voyage, si le graphe l'autorise."""
    payload = event.payload
    to_status = payload.get("to_status")
    if not to_status:
        raise EventRejected("to_status manquant dans le payload.")
    if to_status not in Trip.Status.values:
        raise EventRejected(f"Statut inconnu : {to_status}")

    trip_id = payload.get("trip_id")
    if trip_id:
        trip = Trip.objects.filter(tenant=tenant, id=trip_id).first()
        if trip is None:
            raise EventRejected(f"Voyage {trip_id} introuvable.")
    else:
        trip = session.trip

    # Placé après le if/else — trivialement vrai dans la branche session.trip,
    # mais le check ne doit pas dépendre de la façon dont le trip a été résolu.
    # Sans lui, un contrôleur ouvert sur le voyage A peut faire transiter le
    # voyage B de son tenant en forgeant payload.trip_id.
    if trip.id != session.trip_id:
        raise EventRejected(
            f"Le trip cible ({trip.id}) ne correspond pas au trip "
            f"de la session ({session.trip_id})."
        )

    allowed = ALLOWED_TRANSITIONS.get(trip.status, set())
    if to_status not in allowed:
        raise EventRejected(f"Transition interdite : {trip.status} → {to_status}")

    update_fields = ["status", "updated_at"]
    trip.status = to_status
    if to_status == Trip.Status.IN_TRANSIT and trip.actual_departure_at is None:
        trip.actual_departure_at = event.created_at_local
        update_fields.append("actual_departure_at")
    trip.save(update_fields=update_fields)

    return {
        "status": "accepted",
        "anomaly": None,
        "trip_id": str(trip.id),
        "trip_status": trip.status,
    }
