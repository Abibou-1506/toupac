"""
TOUPAC Voyage — Traitement des batches d'events offline.

Port du ControlEventProcessor Fleetbase (Sprint 2). L'app contrôleur travaille
hors réseau, accumule ses events localement, puis les rejoue en bloc au retour
de la connexion — d'où l'idempotence par client_uuid et le verdict par event.
"""
import logging
import uuid
from datetime import datetime, timezone as dt_timezone

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from voyage.models import ControlEvent
from voyage.services.exceptions import EventRejected
from voyage.services.handlers import (
    anomalies, boarding, incidents, parcels, sales, transitions,
)

logger = logging.getLogger(__name__)

EVENT_HANDLERS = {
    "reservation_board": boarding.handle_board,
    "reservation_refuse": boarding.handle_refuse,
    "reservation_special_case": boarding.handle_special_case,
    "onboard_sale": sales.handle_onboard_sale,
    "anomaly_create": anomalies.handle_anomaly_create,
    "anomaly_resolve": anomalies.handle_anomaly_resolve,
    "incident_create": incidents.handle_incident_create,
    "activity_transition": transitions.handle_activity_transition,
    "parcel_verify": parcels.handle_parcel_verify,
    "parcel_refuse": parcels.handle_parcel_refuse,
}

# Trie les events non horodatés en fin de batch plutôt que de planter.
_FAR_FUTURE = datetime.max.replace(tzinfo=dt_timezone.utc)


class BatchEventProcessor:
    """
    Traite un batch d'events offline envoyés par l'app contrôleur.

    Garanties :
    - Idempotence : un event dont le client_uuid a déjà été traité est ignoré
      (verdict "duplicate", pas d'erreur) ;
    - Atomicité par event : chaque handler s'exécute dans son propre savepoint,
      un échec n'annule que cet event — le reste du batch continue ;
    - Ordre : les events sont traités dans l'ordre d'émission (created_at_local) ;
    - Auto-anomalies : les incohérences sont détectées et loguées automatiquement.
    """

    def __init__(self, session, tenant, user):
        self.session = session
        self.tenant = tenant
        self.user = user

    # ─── API publique ───

    def process_batch(self, events_data):
        """Traite une liste d'events et retourne un verdict par event."""
        ordered = sorted(
            enumerate(events_data),
            key=lambda pair: (self._sort_key(pair[1]), pair[0]),
        )
        return [self._process_single_event(event_data) for _, event_data in ordered]

    # ─── Traitement unitaire ───

    def _process_single_event(self, event_data):
        """Traite un event unique dans sa propre transaction DB."""
        if not isinstance(event_data, dict):
            return self._verdict(None, "rejected", "Event mal formé (objet attendu).")

        raw_uuid = event_data.get("client_uuid")
        try:
            client_uuid = uuid.UUID(str(raw_uuid))
        except (TypeError, ValueError):
            return self._verdict(raw_uuid, "rejected", "client_uuid manquant ou invalide.")

        # 1. Idempotence
        if ControlEvent.objects.filter(tenant=self.tenant, client_uuid=client_uuid).exists():
            return self._verdict(client_uuid, "duplicate")

        event_type = event_data.get("event_type")
        if not event_type:
            return self._verdict(client_uuid, "rejected", "event_type manquant.")

        created_at_local = self._parse_datetime(event_data.get("created_at_local"))
        if created_at_local is None:
            return self._verdict(client_uuid, "rejected", "created_at_local manquant ou invalide.")

        try:
            gps_location = self._parse_point(event_data.get("gps_location"))
        except (TypeError, ValueError, KeyError):
            return self._verdict(client_uuid, "rejected", "gps_location invalide.")

        try:
            target_id = self._parse_uuid(event_data.get("target_id"))
        except ValueError:
            return self._verdict(client_uuid, "rejected", "target_id invalide.")

        try:
            with transaction.atomic():
                # 2. L'event est archivé quel que soit le verdict : c'est lui qui
                #    porte la garantie d'idempotence lors d'un rejeu du batch.
                event = ControlEvent.objects.create(
                    tenant=self.tenant,
                    session=self.session,
                    client_uuid=client_uuid,
                    event_type=event_type,
                    target_type=event_data.get("target_type") or "",
                    target_id=target_id,
                    payload=event_data.get("payload") or {},
                    gps_location=gps_location,
                    gps_accuracy_m=event_data.get("gps_accuracy_m"),
                    created_at_local=created_at_local,
                )

                # 3. Dispatch — savepoint dédié : un échec n'annule que le handler.
                try:
                    with transaction.atomic():
                        result = self._dispatch(event)
                except EventRejected as exc:
                    result = {"status": "rejected", "rejection_reason": str(exc)}
                except Exception as exc:  # noqa: BLE001 — un event ne doit jamais tuer le batch
                    logger.exception(
                        "Échec du traitement de l'event %s (%s)", client_uuid, event_type,
                    )
                    result = {"status": "rejected", "rejection_reason": f"Erreur interne : {exc}"}

                # 4. Verdict persisté sur l'event
                accepted = result.get("status") == "accepted"
                event.status = ControlEvent.Status.PROCESSED if accepted else ControlEvent.Status.REJECTED
                event.rejection_reason = (result.get("rejection_reason") or "")[:200]
                event.processed_at = timezone.now()
                event.save(update_fields=["status", "rejection_reason", "processed_at", "updated_at"])
        except IntegrityError:
            # Course entre deux batches concurrents sur le même client_uuid.
            return self._verdict(client_uuid, "duplicate")
        except Exception as exc:  # noqa: BLE001 — archivage impossible, event perdu
            logger.exception("Impossible d'archiver l'event %s (%s)", client_uuid, event_type)
            return self._verdict(client_uuid, "rejected", f"Event inexploitable : {exc}")

        return self._verdict(
            client_uuid,
            result.get("status", "accepted"),
            result.get("rejection_reason"),
            result.get("anomaly"),
        )

    def _dispatch(self, event):
        """Route l'event vers son handler."""
        handler = EVENT_HANDLERS.get(event.event_type)
        if handler is None:
            raise EventRejected(f"Type d'event inconnu : {event.event_type}")
        return handler(event, self.tenant, self.session)

    # ─── Helpers ───

    @staticmethod
    def _verdict(client_uuid, status, rejection_reason=None, anomaly=None):
        verdict = {
            "client_uuid": str(client_uuid) if client_uuid else None,
            "status": status,
            "anomaly": anomaly,
        }
        if rejection_reason:
            verdict["rejection_reason"] = rejection_reason
        return verdict

    @staticmethod
    def _parse_uuid(value):
        """Retourne un UUID, ou None si la valeur est absente. Lève ValueError si invalide."""
        if value in (None, ""):
            return None
        return uuid.UUID(str(value))

    @staticmethod
    def _parse_datetime(value):
        """Parse un datetime ISO et le rend timezone-aware (USE_TZ=True)."""
        if not value:
            return None
        parsed = parse_datetime(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @staticmethod
    def _parse_point(gps_data):
        """{"lat": ..., "lng": ...} → Point(lng, lat, srid=4326)."""
        if not gps_data:
            return None
        return Point(float(gps_data["lng"]), float(gps_data["lat"]), srid=4326)

    @classmethod
    def _sort_key(cls, event_data):
        if not isinstance(event_data, dict):
            return _FAR_FUTURE
        return cls._parse_datetime(event_data.get("created_at_local")) or _FAR_FUTURE
