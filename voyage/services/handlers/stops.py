"""
TOUPAC Voyage — Handlers d'arrivée et de départ aux escales.

Deux événements dédiés, décorrélés de la transition de statut du trip. Un
`activity_transition at_stop` dit « le voyage est à l'arrêt » ; `stop_arrive`
dit **quelle escale** est atteinte, et pose l'horodatage qui permettra la
ponctualité par étape. Le découplage est intentionnel :

- Le tracking GPS automatique à venir émettra ces mêmes événements sans
  toucher au statut métier. Si l'écriture du statut vivait ici, elle entrerait
  en conflit avec l'autre émetteur.
- La règle « un handler fait une chose » : marquer une escale et transiter un
  statut sont deux intentions. L'app contrôleur mobile fait les deux en
  émettant deux events séparés, ce qui laisse chaque savepoint indépendant —
  une des deux écritures peut échouer sans annuler l'autre.

Trois décisions tolérantes codées ici, documentées à chaque fois :

- Pas de contrôle d'ordre `ata` avant `atd`. Un contrôleur qui émet `depart`
  sans `arrive` a plus probablement oublié le premier geste que l'inverse.
- Pas de rejet sur double marquage : on écrase `ata`/`atd` sans râler. Le vrai
  doublon est tranché en amont par l'idempotence `client_uuid` du batch.
- Pas de dépendance avec `Trip.status`. L'app peut émettre dans l'ordre
  qu'elle veut, le tracking GPS futur n'aura pas cette information.
"""
from voyage.models import TripStop
from voyage.services.exceptions import EventRejected, RejectionCode


def handle_stop_arrive(event, tenant, session):
    """Marque l'arrivée à une escale du voyage courant."""
    stop = _resolve_stop(event, session)
    stop.ata = event.created_at_local
    stop.status = TripStop.Status.ARRIVED
    stop.save(update_fields=["ata", "status", "updated_at"])
    return {
        "status": "accepted",
        "anomaly": None,
        "stop_id": str(stop.id),
        "stop_status": stop.status,
    }


def handle_stop_depart(event, tenant, session):
    """Marque le départ d'une escale du voyage courant."""
    stop = _resolve_stop(event, session)
    stop.atd = event.created_at_local
    stop.status = TripStop.Status.DEPARTED
    stop.save(update_fields=["atd", "status", "updated_at"])
    return {
        "status": "accepted",
        "anomaly": None,
        "stop_id": str(stop.id),
        "stop_status": stop.status,
    }


def _resolve_stop(event, session):
    """
    Le `TripStop` ciblé par l'event, vérifié contre le trip de la session.

    Le payload porte `stop_id`, qui référence un `TripStop` — l'instance
    datée — et non un `RouteStop`, modèle de référence stable. L'app lit
    `trip.stops[i].id` dans le manifest et l'envoie tel quel.

    Le filtre `trip=session.trip` fait d'une pierre deux coups : il refuse les
    stops d'autres voyages, et à travers eux les stops d'autres tenants, puisque
    la session appartient déjà au tenant courant. Pas besoin de filtre tenant
    séparé — l'ancrage par la session est plus serré qu'un `tenant=tenant`.
    """
    payload = event.payload
    stop_id = payload.get("stop_id")
    if not stop_id:
        raise EventRejected(
            "stop_id manquant dans le payload.",
            RejectionCode.MISSING_STOP_ID,
        )

    stop = (
        TripStop.objects.filter(id=stop_id, trip=session.trip)
        .select_related("route_stop__place")
        .first()
    )
    if stop is None:
        raise EventRejected(
            f"TripStop {stop_id} inconnu du voyage {session.trip_id}.",
            RejectionCode.STOP_NOT_FOUND,
        )
    return stop
