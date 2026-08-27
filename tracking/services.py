"""TOUPAC Tracking — Synchronisation Traccar et détection de géofences."""
from django.contrib.gis.geos import Point
from django.utils import timezone

from .models import Geofence, GeofenceEvent, Position


class TraccarBridge:
    """
    Sync positions depuis Traccar → PostgreSQL.
    V1 : mock (insertion directe des positions reçues). V2 : appel API REST Traccar.
    """

    @staticmethod
    def sync_positions(tenant, vehicle, positions_data):
        """
        Insère un batch de positions en DB via bulk_create.

        positions_data = [{"lat": float, "lng": float, "speed": float,
                           "heading": float, "accuracy": int, "recorded_at": str}, ...]
        """
        positions = []
        for p in positions_data:
            positions.append(Position(
                tenant=tenant,
                vehicle=vehicle,
                location=Point(p["lng"], p["lat"], srid=4326),
                speed_kmh=p.get("speed"),
                heading=p.get("heading"),
                accuracy_m=p.get("accuracy"),
                altitude_m=p.get("altitude"),
                source=p.get("source", "driver_app"),
                recorded_at=p["recorded_at"],
            ))
        return Position.objects.bulk_create(positions)

    @staticmethod
    def get_vehicle_last_position(vehicle_id):
        """Retourne la dernière position connue d'un véhicule (ordering=-recorded_at)."""
        return Position.objects.filter(vehicle_id=vehicle_id).first()


class GeofenceChecker:
    """Vérifie si un véhicule est dans une géofence et journalise les transitions."""

    @staticmethod
    def check_position(tenant, vehicle, point):
        """
        Pour chaque geofence active du tenant, vérifie si le point est dans
        le boundary. Si une transition entrée/sortie est détectée par rapport
        au dernier event connu, crée un GeofenceEvent.

        V1 : implémentation basique avec Polygon.contains (ST_Contains).
        """
        active_fences = Geofence.objects.filter(tenant=tenant, is_active=True)

        events_created = []
        for fence in active_fences:
            is_inside = fence.boundary.contains(point)
            last_event = GeofenceEvent.objects.filter(
                tenant=tenant, geofence=fence, vehicle=vehicle,
            ).first()

            was_inside = last_event is not None and last_event.event_type == GeofenceEvent.EventType.ENTER

            if is_inside and not was_inside:
                event = GeofenceEvent.objects.create(
                    tenant=tenant, geofence=fence, vehicle=vehicle,
                    event_type=GeofenceEvent.EventType.ENTER, event_at=timezone.now(),
                )
                events_created.append(event)
            elif not is_inside and was_inside:
                event = GeofenceEvent.objects.create(
                    tenant=tenant, geofence=fence, vehicle=vehicle,
                    event_type=GeofenceEvent.EventType.EXIT, event_at=timezone.now(),
                )
                events_created.append(event)

        return events_created
