"""TOUPAC Voyage — Handler de vente à bord (billet émis par le contrôleur)."""
from django.db.models import F

from voyage.models import Anomaly, CashEntry, Passenger, Reservation, RouteStop, Trip
from voyage.services.anomaly_detectors import serialize_anomaly
from voyage.services.exceptions import EventRejected, RejectionCode
from voyage.services.qr_jwt import sign_ticket_jwt
from voyage.services.seat_map import trip_seat_labels

#: Moyens de paiement acceptés pour une vente à bord. Les quatre opérateurs
#: mobiles y figurent : un contrôleur peut légitimement encaisser par Wave
#: plutôt qu'en espèces. Le champ n'avait aucune validation — n'importe quelle
#: chaîne passait, faute de frappe comprise, et le handler forçait de toute
#: façon « onboard_cash » par-dessus ce que l'app envoyait.
ALLOWED_PAYMENT_METHODS = frozenset({
    "cash", "wave", "orange_money", "free_money", "mtn_momo", "onboard_cash",
})

#: Défaut historique, préservé : les appelants actuels n'envoient pas le champ.
DEFAULT_PAYMENT_METHOD = "onboard_cash"

#: Statuts qui libèrent un siège. Exprimé en exclusion et repris **tel quel**
#: de la contrainte `unique_active_seat_per_trip`. Si la vérification en amont
#: et le filet en base ne couvraient pas le même ensemble, un cas passerait la
#: première pour tomber en `IntegrityError` sur le second — soit exactement le
#: défaut que ce handler est censé supprimer. `no_show` en fait donc partie :
#: le siège reste attribué à qui ne s'est pas présenté.
VOID_RESERVATION_STATUSES = ("cancelled", "refused")


def handle_onboard_sale(event, tenant, session):
    """
    Vend un billet à bord : crée (ou réutilise) le passager, la réservation
    déjà embarquée, et l'encaissement correspondant.

    Quatre vérifications précèdent l'écriture, car un contrôleur travaille hors
    réseau et sa saisie n'est arbitrée par rien avant d'arriver ici :

    - le passager porte un nom — sans quoi le billet désigne un fantôme ;
    - le siège existe dans le plan du voyage, quand un plan est déclaré ;
    - le siège n'est pas déjà attribué — anomalie et rejet propre sinon ;
    - le moyen de paiement appartient à une liste fermée.
    """
    payload = event.payload
    passenger_data = payload.get("passenger_data") or payload.get("passenger") or {}
    seat_label = payload.get("seat_label")
    amount_xof = payload.get("amount_xof")

    if not seat_label:
        raise EventRejected(
            "seat_label manquant dans le payload.", RejectionCode.MISSING_SEAT_LABEL,
        )
    if amount_xof is None:
        raise EventRejected(
            "amount_xof manquant dans le payload.", RejectionCode.MISSING_AMOUNT,
        )

    first_name = (passenger_data.get("first_name") or "").strip()
    last_name = (passenger_data.get("last_name") or "").strip()
    if not first_name or not last_name:
        # `phone` reste facultatif : il ne sert qu'à retrouver une fiche
        # existante, pas à identifier le voyageur.
        raise EventRejected(
            "passenger_data incomplet : first_name et last_name sont requis.",
            RejectionCode.MISSING_PASSENGER_DATA,
        )

    payment_method = payload.get("payment_method") or DEFAULT_PAYMENT_METHOD
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise EventRejected(
            f"Moyen de paiement non reconnu : {payment_method}.",
            RejectionCode.INVALID_PAYMENT_METHOD,
        )

    trip_id = payload.get("trip_id")
    if trip_id:
        trip = (
            Trip.objects.filter(tenant=tenant, id=trip_id)
            .select_related("seat_map").first()
        )
        if trip is None:
            raise EventRejected(
                f"Voyage {trip_id} introuvable.", RejectionCode.TRIP_NOT_FOUND,
            )
    else:
        trip = session.trip

    _reject_unknown_seat(trip, seat_label)
    origin_stop, destination_stop = _resolve_stops(tenant, trip, payload)

    conflict = _seat_conflict_verdict(event, tenant, session, trip, seat_label)
    if conflict is not None:
        # Rejet « propre », par retour et non par exception : `EventRejected`
        # ferait rollback du savepoint et effacerait l'anomalie qui motive le
        # refus. Même parti que `handle_board` sur son propre conflit.
        return conflict

    # Réutilise le passager si son téléphone est déjà connu du tenant.
    phone = (passenger_data.get("phone") or "").strip()
    passenger = None
    if phone:
        passenger = Passenger.objects.filter(
            tenant=tenant, phone=phone, deleted_at__isnull=True,
        ).first()
    if passenger is None:
        passenger = Passenger.objects.create(
            tenant=tenant, first_name=first_name, last_name=last_name, phone=phone,
        )

    reservation = Reservation.objects.create(
        tenant=tenant,
        trip=trip,
        passenger=passenger,
        seat_label=seat_label,
        origin_stop=origin_stop,
        destination_stop=destination_stop,
        status=Reservation.Status.BOARDED,
        amount_xof=amount_xof,
        payment_method=payment_method,
        # Codés en dur, et ce n'est pas un oubli : une vente à bord est par
        # définition une saisie manuelle sur le canal « onboard ».
        sales_channel="onboard",
        boarding_method="manual",
        boarded_at=event.created_at_local,
        boarded_by=session.controller,
    )

    # Même geste que la vue classique de création de réservation (POST
    # /voyage/reservations/) : un billet sans JWT n'a pas de preuve d'achat
    # vérifiable par un relais de contrôleur plus loin sur la route, et un
    # tel billet forme une famille à part dans toutes les requêtes futures.
    # L'omission historique a été corrigée au ticket du 2 oct 2026.
    reservation.qr_code_jwt = sign_ticket_jwt(reservation)
    reservation.save(update_fields=["qr_code_jwt"])

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
        "origin_stop_id": str(reservation.origin_stop_id),
        "destination_stop_id": str(reservation.destination_stop_id),
        "reservation_status": reservation.status,
        "trip_status": trip.status,
    }


def _resolve_stops(tenant, trip, payload):
    """
    Résout `origin_stop` et `destination_stop` du payload, les valide, les rend.

    L'ordre des rejets suit celui qu'un dev mobile verra le plus souvent :
    champ absent → stop inconnu → ordre invalide → flag d'usage. Un stop qui
    appartient à une autre route est traité comme **inconnu** — pour ce trip,
    il n'existe pas, même s'il existe en base. La seule requête charge les
    deux stops ensemble pour éviter deux allers-retours.

    Les deux stops sont obligatoires : un contrôleur qui vend à bord sait
    toujours où le passager monte (il le voit) et où il descend (il lui
    demande, c'est le prix du billet).
    """
    origin_stop_id = payload.get("origin_stop")
    destination_stop_id = payload.get("destination_stop")

    if not origin_stop_id:
        raise EventRejected(
            "origin_stop manquant dans le payload.",
            RejectionCode.MISSING_ORIGIN_STOP,
        )
    if not destination_stop_id:
        raise EventRejected(
            "destination_stop manquant dans le payload.",
            RejectionCode.MISSING_DESTINATION_STOP,
        )

    stops_by_id = {
        str(stop.id): stop
        for stop in RouteStop.objects.filter(
            tenant=tenant, route=trip.route,
            id__in=[origin_stop_id, destination_stop_id],
        ).select_related("place")
    }

    origin_stop = stops_by_id.get(str(origin_stop_id))
    if origin_stop is None:
        raise EventRejected(
            f"origin_stop {origin_stop_id} inconnu de la route de ce voyage.",
            RejectionCode.INVALID_ORIGIN_STOP,
        )
    destination_stop = stops_by_id.get(str(destination_stop_id))
    if destination_stop is None:
        raise EventRejected(
            f"destination_stop {destination_stop_id} inconnu de la route "
            "de ce voyage.",
            RejectionCode.INVALID_DESTINATION_STOP,
        )

    if origin_stop.stop_order >= destination_stop.stop_order:
        raise EventRejected(
            f"Ordre des escales invalide : "
            f"origin.stop_order={origin_stop.stop_order} doit être strictement "
            f"inférieur à destination.stop_order={destination_stop.stop_order}.",
            RejectionCode.INVALID_STOP_ORDER,
        )

    if not origin_stop.is_boarding:
        raise EventRejected(
            f"Embarquement non autorisé à l'escale {origin_stop.place.name}.",
            RejectionCode.BOARDING_NOT_ALLOWED_AT_STOP,
        )
    if not destination_stop.is_alighting:
        raise EventRejected(
            f"Débarquement non autorisé à l'escale {destination_stop.place.name}.",
            RejectionCode.ALIGHTING_NOT_ALLOWED_AT_STOP,
        )

    return origin_stop, destination_stop


def _reject_unknown_seat(trip, seat_label):
    """Refuse un siège absent du plan — ne fait rien si aucun plan n'est déclaré."""
    labels = trip_seat_labels(trip)
    # Une liste vide vaut « aucun plan déclaré », pas « plan vide » : un voyage
    # sans `seat_map` est une configuration légitime, et y refuser tous les
    # sièges rendrait la vente à bord impossible. On ne valide pas ce qui n'est
    # pas déclaré — la vérification d'occupation, elle, s'applique toujours.
    if labels and seat_label not in labels:
        raise EventRejected(
            f"Siège {seat_label} absent du plan du voyage {trip.internal_id}.",
            RejectionCode.INVALID_SEAT_LABEL,
        )


def _seat_conflict_verdict(event, tenant, session, trip, seat_label):
    """Verdict de rejet si le siège est déjà attribué, sinon `None`."""
    taken = (
        Reservation.objects.filter(tenant=tenant, trip=trip, seat_label=seat_label)
        .exclude(status__in=VOID_RESERVATION_STATUSES)
        .exists()
    )
    if not taken:
        return None

    anomaly = Anomaly.objects.create(
        tenant=tenant,
        session=session,
        event=event,
        type=Anomaly.Type.SEAT_CONFLICT,
        # Modérée, et non critique comme dans `detect_seat_conflict` : là-bas,
        # deux passagers sont déjà embarqués sur le même siège — le conflit a
        # eu lieu. Ici il est empêché, la vente est refusée, personne ne
        # s'assoit. Alerter en « critique » sur ce que le système vient de
        # bloquer viderait ce niveau de son sens.
        severity=Anomaly.Severity.MODERATE,
        title=f"Siège {seat_label} déjà attribué — {trip.internal_id}"[:200],
        description=(
            f"Vente à bord refusée : le siège {seat_label} du voyage "
            f"{trip.internal_id} porte déjà une réservation active."
        ),
        target_type="trip",
        target_id=trip.id,
    )
    return {
        "status": "rejected",
        "rejection_reason": f"Siège {seat_label} déjà occupé sur ce voyage.",
        "rejection_code": RejectionCode.SEAT_ALREADY_TAKEN,
        "anomaly": serialize_anomaly(anomaly),
    }
