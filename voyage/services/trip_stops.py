"""
TOUPAC Voyage — Utilitaires de materialisation des TripStop.

Logique partagee entre :
- Le signal post_save(sender=Trip) dans voyage/signals.py (automatique a la
  creation d'un Trip)
- La commande management materialize_missing_tripstops (rattrapage manuel
  des Trips historiques crees avant le signal du 7 oct 2026)

Zero duplication : le signal appelle `materialize_trip_stops` directement.
"""
from datetime import timedelta

from voyage.models import Trip, TripStop


def materialize_trip_stops(trip: Trip) -> int:
    """
    Materialise les TripStop d'un Trip depuis les RouteStop ordonnes de sa route.

    Idempotent : si des TripStop existent deja pour ce voyage, retourne 0 sans
    rien ecrire. Sinon, cree un TripStop par RouteStop en bulk et retourne le
    nombre cree.

    `eta = trip.scheduled_at + timedelta(minutes=rs.arrival_offset_minutes)`
    (V1.1 Prompt 3 : arrival_offset_minutes distinct de departure_offset_minutes).
    """
    if trip.stops.exists():
        return 0
    route_stops = list(trip.route.stops.order_by("stop_order"))
    if not route_stops:
        return 0
    TripStop.objects.bulk_create([
        TripStop(
            tenant=trip.tenant,
            trip=trip,
            route_stop=rs,
            place=rs.place,
            stop_order=rs.stop_order,
            eta=trip.scheduled_at + timedelta(minutes=rs.arrival_offset_minutes),
            status=TripStop.Status.PENDING,
        )
        for rs in route_stops
    ])
    return len(route_stops)
