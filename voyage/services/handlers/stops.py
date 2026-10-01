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

Trois décisions codées ici, documentées à chaque fois :

- **Pas de contrôle d'ordre `ata` avant `atd`.** Un contrôleur qui émet
  `depart` sans `arrive` a plus probablement oublié le premier geste que
  l'inverse.
- **Pas de rejet sur double marquage, mais « premier gagne » sur l'horodatage.**
  Le vrai doublon est tranché en amont par l'idempotence `client_uuid` ; un
  resync qui régénère cet UUID est un défaut d'app, et l'instant réel du
  premier passage reste la vérité à garder. Le status, lui, est remis à jour
  à chaque appel — c'est un état courant, pas un fait historique.
- **Pas de dépendance avec `Trip.status`.** L'app peut émettre dans l'ordre
  qu'elle veut, le tracking GPS futur n'aura pas cette information.
"""
from voyage.models import TripStop
from voyage.services.exceptions import EventRejected, RejectionCode


def handle_stop_arrive(event, tenant, session):
    """Marque l'arrivée à une escale du voyage courant."""
    stop = _resolve_stop(event, session)
    _apply_timestamp(stop, "ata", TripStop.Status.ARRIVED, event.created_at_local)
    return {
        "status": "accepted",
        "anomaly": None,
        "stop_id": str(stop.id),
        "stop_status": stop.status,
    }


def handle_stop_depart(event, tenant, session):
    """Marque le départ d'une escale du voyage courant."""
    stop = _resolve_stop(event, session)
    _apply_timestamp(stop, "atd", TripStop.Status.DEPARTED, event.created_at_local)
    return {
        "status": "accepted",
        "anomaly": None,
        "stop_id": str(stop.id),
        "stop_status": stop.status,
    }


def _apply_timestamp(stop, field, new_status, when):
    """
    Pose l'horodatage et met le status à jour, selon deux règles distinctes.

    **Horodatage : premier gagne.** Un `stop_arrive` sur un stop déjà `ata`
    laisse la valeur initiale intacte — même pattern que
    `handle_activity_transition` sur `actual_departure_at` et
    `actual_arrival_at`. Un bug de resync qui régénérerait le `client_uuid`
    passerait l'idempotence du batch sans la bloquer, et écraser l'instant
    réel du premier passage serait pire que de l'ignorer : on ne saurait
    plus à quelle heure le trip est passé.

    **Status : toujours mis à jour.** C'est l'état courant, pas un fait
    historique — un stop à tort marqué `SKIPPED` doit pouvoir être remis à
    `ARRIVED` par un geste explicite. Les deux règles vivent ensemble parce
    qu'elles répondent à deux questions distinctes.
    """
    update_fields = []
    if getattr(stop, field) is None:
        setattr(stop, field, when)
        update_fields.append(field)
    if stop.status != new_status:
        stop.status = new_status
        update_fields.append("status")
    if update_fields:
        update_fields.append("updated_at")
        stop.save(update_fields=update_fields)


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
