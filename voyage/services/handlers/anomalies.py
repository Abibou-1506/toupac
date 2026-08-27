"""TOUPAC Voyage — Handlers d'anomalies déclarées par le contrôleur."""
from django.utils import timezone

from voyage.models import Anomaly
from voyage.services.anomaly_detectors import serialize_anomaly
from voyage.services.exceptions import EventRejected


def handle_anomaly_create(event, tenant, session):
    """Enregistre une anomalie signalée manuellement depuis l'app contrôleur."""
    payload = event.payload
    title = payload.get("title")
    if not title:
        raise EventRejected("title manquant dans le payload.")

    anomaly = Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=payload.get("type", Anomaly.Type.OTHER),
        severity=payload.get("severity", Anomaly.Severity.LOW),
        title=title[:200],
        description=payload.get("description", ""),
        target_type=payload.get("target_type", ""),
        target_id=payload.get("target_id"),
        evidence_urls=payload.get("evidence_urls", []),
    )

    return {"status": "accepted", "anomaly": serialize_anomaly(anomaly)}


def handle_anomaly_resolve(event, tenant, session):
    """Clôture une anomalie depuis le terrain."""
    anomaly_id = event.payload.get("anomaly_id") or event.target_id
    if not anomaly_id:
        raise EventRejected("anomaly_id manquant dans le payload.")

    anomaly = Anomaly.objects.filter(tenant=tenant, id=anomaly_id).first()
    if anomaly is None:
        raise EventRejected(f"Anomalie {anomaly_id} introuvable.")

    anomaly.status = Anomaly.Status.RESOLVED
    anomaly.resolved_at = timezone.now()
    anomaly.resolution_notes = event.payload.get("resolution_notes", "")
    anomaly.resolved_by = session.controller.user
    anomaly.save(update_fields=[
        "status", "resolved_at", "resolution_notes", "resolved_by", "updated_at",
    ])

    return {"status": "accepted", "anomaly": serialize_anomaly(anomaly)}
