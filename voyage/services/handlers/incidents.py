"""TOUPAC Voyage — Handler d'incidents signalés à bord."""
from voyage.models import Incident, Trip
from voyage.services.exceptions import EventRejected


def handle_incident_create(event, tenant, session):
    """Enregistre un incident (bagage, comportement, sécurité, panne...)."""
    payload = event.payload
    title = payload.get("title")
    if not title:
        raise EventRejected("title manquant dans le payload.")

    trip_id = payload.get("trip_id")
    if trip_id:
        trip = Trip.objects.filter(tenant=tenant, id=trip_id).first()
        if trip is None:
            raise EventRejected(f"Voyage {trip_id} introuvable.")
    else:
        trip = session.trip

    incident = Incident.objects.create(
        tenant=tenant,
        session=session,
        trip=trip,
        reporter=session.controller.user,
        type=payload.get("type", Incident.Type.OTHER),
        severity=payload.get("severity", Incident.Severity.LOW),
        title=title[:200],
        description=payload.get("description", ""),
        photos_urls=payload.get("photos_urls", []),
        gps_location=event.gps_location,
        gps_address=payload.get("gps_address", ""),
    )

    return {
        "status": "accepted",
        "anomaly": None,
        "incident_id": str(incident.id),
    }
