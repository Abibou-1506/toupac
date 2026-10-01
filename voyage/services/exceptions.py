"""TOUPAC Voyage — Exceptions et codes de rejet du protocole offline-sync."""
from enum import StrEnum


class RejectionCode(StrEnum):
    """
    Motifs de rejet d'un event, sous forme stable et exploitable par un client.

    `rejection_reason` reste du français libre, destiné à l'œil. Ce code-ci est
    destiné au code : l'app contrôleur en déduit quoi faire — réessayer plus
    tard, corriger la saisie, abandonner l'event, alerter l'utilisateur — ce
    qu'un message traduit ou reformulé ne permet pas.

    L'énumération vit ici et non en `choices` sur le modèle : elle évoluera
    plus vite qu'on n'écrit des migrations, et un code inconnu en base est un
    défaut de code, pas une donnée à valider. Un test vérifie que tout code
    écrit lui appartient.

    `StrEnum` pour que `RejectionCode.X` se sérialise en JSON sans conversion.
    """

    # ── Couche batch : l'event n'atteint pas son handler ──
    MALFORMED_EVENT = "MALFORMED_EVENT"
    INVALID_CLIENT_UUID = "INVALID_CLIENT_UUID"
    MISSING_EVENT_TYPE = "MISSING_EVENT_TYPE"
    INVALID_CREATED_AT = "INVALID_CREATED_AT"
    INVALID_GPS = "INVALID_GPS"
    INVALID_TARGET_ID = "INVALID_TARGET_ID"
    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    #: Panne inattendue d'un handler. Doit rester rare : tout rejet prévisible
    #: mérite son propre code, c'est ce fourre-tout que l'on cherche à vider.
    INTERNAL_ERROR = "INTERNAL_ERROR"
    #: L'archivage de l'event lui-même a échoué : il est perdu, pas seulement
    #: rejeté. Distinct d'INTERNAL_ERROR, qui laisse une trace en base.
    UNPROCESSABLE_EVENT = "UNPROCESSABLE_EVENT"

    # ── Embarquement (boarding.py) ──
    MISSING_RESERVATION_ID = "MISSING_RESERVATION_ID"
    RESERVATION_NOT_FOUND = "RESERVATION_NOT_FOUND"
    RESERVATION_NOT_BOARDABLE = "RESERVATION_NOT_BOARDABLE"

    # ── Vente à bord (sales.py) ──
    MISSING_SEAT_LABEL = "MISSING_SEAT_LABEL"
    MISSING_AMOUNT = "MISSING_AMOUNT"
    MISSING_PASSENGER_DATA = "MISSING_PASSENGER_DATA"
    INVALID_SEAT_LABEL = "INVALID_SEAT_LABEL"
    SEAT_ALREADY_TAKEN = "SEAT_ALREADY_TAKEN"
    INVALID_PAYMENT_METHOD = "INVALID_PAYMENT_METHOD"
    #: Vente à bord sur trajet partiel — un contrôleur sait toujours où monte
    #: et où descend un passager qu'il voit s'asseoir et à qui il demande sa
    #: destination. Les deux stops sont obligatoires, et validés contre la
    #: route du trip (code INVALID_*) plus les flags d'usage (BOARDING/
    #: ALIGHTING_NOT_ALLOWED_AT_STOP). Un stop d'une autre route est traité
    #: comme inconnu : il n'existe pas « pour ce trip », même s'il existe en base.
    MISSING_ORIGIN_STOP = "MISSING_ORIGIN_STOP"
    MISSING_DESTINATION_STOP = "MISSING_DESTINATION_STOP"
    INVALID_ORIGIN_STOP = "INVALID_ORIGIN_STOP"
    INVALID_DESTINATION_STOP = "INVALID_DESTINATION_STOP"
    INVALID_STOP_ORDER = "INVALID_STOP_ORDER"
    BOARDING_NOT_ALLOWED_AT_STOP = "BOARDING_NOT_ALLOWED_AT_STOP"
    ALIGHTING_NOT_ALLOWED_AT_STOP = "ALIGHTING_NOT_ALLOWED_AT_STOP"

    # ── Anomalies (anomalies.py) ──
    MISSING_ANOMALY_ID = "MISSING_ANOMALY_ID"
    ANOMALY_NOT_FOUND = "ANOMALY_NOT_FOUND"

    # ── Colis (parcels.py) ──
    MISSING_PARCEL_ID = "MISSING_PARCEL_ID"
    PARCEL_NOT_FOUND = "PARCEL_NOT_FOUND"

    # ── Transitions de voyage (transitions.py) ──
    MISSING_TO_STATUS = "MISSING_TO_STATUS"
    INVALID_TRIP_STATUS = "INVALID_TRIP_STATUS"
    TRANSITION_NOT_ALLOWED = "TRANSITION_NOT_ALLOWED"
    #: Le trip visé n'est pas celui de la session : tentative de faire transiter
    #: un voyage voisin en forgeant `payload.trip_id`.
    TRIP_NOT_IN_SESSION = "TRIP_NOT_IN_SESSION"

    # ── Partagés par plusieurs handlers ──
    #: `sales`, `incidents`, `transitions` résolvent tous un trip par payload.
    TRIP_NOT_FOUND = "TRIP_NOT_FOUND"
    #: `anomalies` et `incidents` exigent tous deux un titre.
    MISSING_TITLE = "MISSING_TITLE"


class EventRejected(Exception):
    """
    Rejet d'un event offline avec rollback complet de ses side-effects.

    Un handler qui lève cette exception fait rollback du savepoint : rien de ce
    qu'il a écrit n'est conservé. Pour un rejet qui DOIT garder ses side-effects
    (typiquement l'anomalie auto-détectée qui motive le rejet), le handler
    retourne à la place un dict {"status": "rejected", "rejection_reason": ...,
    "rejection_code": ...}.

    `code` a un défaut pour ne pas casser un appelant qui l'omettrait, mais
    aucun `raise` du projet ne s'appuie dessus — un test le vérifie. Le défaut
    est un filet, pas une facilité.
    """

    def __init__(self, message, code=RejectionCode.INTERNAL_ERROR):
        super().__init__(message)
        self.code = code
