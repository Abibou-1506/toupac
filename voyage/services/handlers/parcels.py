"""
TOUPAC Voyage — Handlers colis à bord.

Cas métier : un expéditeur confie un colis au chauffeur d'un bus passagers pour
remise à l'arrivée. Le contrôleur vérifie (ou refuse) ces colis au chargement,
comme il contrôle les billets — d'où leur présence dans les batches offline.
"""
from colis.models import Parcel
from voyage.models import Anomaly
from voyage.services.anomaly_detectors import serialize_anomaly
from voyage.services.exceptions import EventRejected


def _load_parcel(event, tenant):
    """Résout le colis ciblé par l'event (payload prioritaire, puis target_id)."""
    parcel_id = event.payload.get("parcel_id") or event.target_id
    if not parcel_id:
        raise EventRejected("parcel_id manquant dans le payload.")
    parcel = Parcel.objects.filter(tenant=tenant, id=parcel_id).first()
    if parcel is None:
        raise EventRejected(f"Colis {parcel_id} introuvable.")
    return parcel


def handle_parcel_verify(event, tenant, session):
    """Le contrôleur confirme qu'un colis est bien à bord."""
    parcel = _load_parcel(event, tenant)

    if parcel.status in (Parcel.Status.CREATED, Parcel.Status.PICKED_UP):
        parcel.status = Parcel.Status.IN_TRANSIT
        parcel.save(update_fields=["status", "updated_at"])

    return {
        "status": "accepted",
        "anomaly": None,
        "parcel_id": str(parcel.id),
        "parcel_status": parcel.status,
    }


def handle_parcel_refuse(event, tenant, session):
    """Le contrôleur refuse un colis (non conforme, dangereux, hors gabarit...)."""
    parcel = _load_parcel(event, tenant)
    reason = event.payload.get("reason", "") or "Non conforme"

    anomaly = Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=Anomaly.Type.PARCEL_NON_CONFORM,
        severity=Anomaly.Severity.MODERATE,
        title=f"Colis refusé : {parcel.tracking_number}"[:200],
        description=reason,
        target_type="parcel",
        target_id=parcel.id,
    )

    return {
        "status": "accepted",
        "anomaly": serialize_anomaly(anomaly),
        "parcel_id": str(parcel.id),
    }
