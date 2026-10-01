"""
TOUPAC Voyage — Exemples de payloads du batch offline pour le Swagger.

Un `payload` dont la forme dépend d'un autre champ est tout ce que
drf-spectacular ne sait pas décrire : la seule prise qu'on peut donner à un dev
mobile sans l'envoyer dans le code des handlers est **l'exemple**.

Les 10 exemples ci-dessous — un par `event_type` — sont tirés de la lecture
des handlers (`voyage/services/handlers/*.py`), jamais inventés. Chaque clé
d'un `payload` d'exemple correspond à une ligne `payload.get("…")` dans son
handler ; les clés que le handler ignore volontairement (parce qu'elles sont
forcées côté serveur, comme `sales_channel` pour `onboard_sale`) ne figurent
pas dans l'exemple, pour ne pas laisser croire qu'elles ont un effet.

Un test de non-régression vérifie que les clés obligatoires de chaque handler
sont présentes dans son exemple — un handler qui change sans mise à jour de
l'exemple rend rouge.
"""
from drf_spectacular.utils import OpenApiExample

#: UUIDv7 stables, visiblement factices (pas des IDs de production).
_SESSION_ID = "0192f3a0-4b1c-7d2e-8f90-a1b2c3d4e5f6"
_TRIP_ID = "49538784-255d-4aaa-b092-b28683a02626"
_RESERVATION_ID = "0192f2ab-1234-7abc-8def-1122334455aa"
_ANOMALY_ID = "0192f2cd-5678-7abc-8def-aabbccddeeff"
_PARCEL_ID = "0192f2ef-9abc-7def-b012-ccddeeff0011"
_CONTROLLER_ID = "0192f300-def0-7123-8456-7890abcdef12"
_DRIVER_USER_ID = "0192f301-aaaa-7bbb-8ccc-dddddddddddd"

_DAKAR = {"lat": 14.6937, "lng": -17.4441}


def _batch(client_uuid, event):
    """Enveloppe standard : un seul event par exemple pour rester lisible."""
    return {"session_id": _SESSION_ID, "events": [event]}


#: Mapping event_type → OpenApiExample. Exposé à la fois à `@extend_schema`
#: (via `list(REQUEST_EXAMPLES.values())`) et aux tests (par clé).
REQUEST_EXAMPLES = {
    "reservation_board": OpenApiExample(
        "Embarquement par scan QR (reservation_board)",
        value=_batch("b7e21c4a-9f3d-4e8b-a1c2-5d6e7f809a1b", {
            "client_uuid": "b7e21c4a-9f3d-4e8b-a1c2-5d6e7f809a1b",
            "event_type": "reservation_board",
            "target_type": "reservation",
            "target_id": _RESERVATION_ID,
            "payload": {
                # `reservation_id` est lu en priorité, `target_id` sert de
                # repli — on envoie les deux par convention.
                "reservation_id": _RESERVATION_ID,
                "boarding_method": "qr_scan",
                # Optionnel : le serveur retombe sur le contrôleur de la
                # session si absent. Utile quand un contrôleur scanne pour
                # un collègue (passage de main).
                "boarded_by_controller_id": _CONTROLLER_ID,
            },
            "created_at_local": "2026-10-01T14:32:07+00:00",
            "gps_location": _DAKAR,
            "gps_accuracy_m": 12,
        }),
        request_only=True,
    ),
    "reservation_refuse": OpenApiExample(
        "Refus d'embarquement (reservation_refuse)",
        value=_batch("c3d4e5f6-7890-4abc-9def-010203040506", {
            "client_uuid": "c3d4e5f6-7890-4abc-9def-010203040506",
            "event_type": "reservation_refuse",
            "target_type": "reservation",
            "target_id": _RESERVATION_ID,
            "payload": {
                "reservation_id": _RESERVATION_ID,
                # Tronqué à 200 caractères côté serveur, mais écrit tel quel.
                "reason": "Billet déjà utilisé par un autre voyageur.",
            },
            "created_at_local": "2026-10-01T14:40:11+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "reservation_special_case": OpenApiExample(
        "Embarquement manuel (reservation_special_case)",
        value=_batch("d4e5f607-8901-4abc-9def-020304050607", {
            "client_uuid": "d4e5f607-8901-4abc-9def-020304050607",
            "event_type": "reservation_special_case",
            "target_type": "reservation",
            "target_id": _RESERVATION_ID,
            "payload": {
                "reservation_id": _RESERVATION_ID,
                "reason": "QR illisible, identité vérifiée par pièce.",
            },
            "created_at_local": "2026-10-01T14:45:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "onboard_sale": OpenApiExample(
        "Vente à bord (onboard_sale)",
        value=_batch("c8f32d5b-0a4e-4f9c-b2d3-6e7f8091ab2c", {
            "client_uuid": "c8f32d5b-0a4e-4f9c-b2d3-6e7f8091ab2c",
            "event_type": "onboard_sale",
            # `target_type` et `target_id` ne sont pas lus par ce handler —
            # la cible est un `Trip`, pas une entité préexistante.
            "payload": {
                # Facultatif : si absent, le serveur prend le trip de la session.
                "trip_id": _TRIP_ID,
                "seat_label": "B1",
                "amount_xof": 25000,
                # Facultatif : défaut `onboard_cash`. Liste blanche fermée —
                # cf. ALLOWED_PAYMENT_METHODS.
                "payment_method": "wave",
                "passenger_data": {
                    "first_name": "Fatou",
                    "last_name": "Mbaye",
                    # Facultatif : sert à retrouver une fiche passager existante.
                    "phone": "+221770000101",
                },
            },
            "created_at_local": "2026-10-01T14:35:12+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "anomaly_create": OpenApiExample(
        "Signalement d'anomalie (anomaly_create)",
        value=_batch("e5f60708-9012-4abc-9def-030405060708", {
            "client_uuid": "e5f60708-9012-4abc-9def-030405060708",
            "event_type": "anomaly_create",
            "payload": {
                "title": "Porte latérale défectueuse",
                # Facultatifs : défauts `other` / `low` si absents.
                "type": "safety",
                "severity": "moderate",
                "description": "La porte se rouvre pendant le trajet.",
                "target_type": "trip",
                "target_id": _TRIP_ID,
                "evidence_urls": [
                    "https://media.toupac.sn/incidents/porte-01.jpg",
                ],
            },
            "created_at_local": "2026-10-01T15:02:30+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "anomaly_resolve": OpenApiExample(
        "Clôture d'anomalie (anomaly_resolve)",
        value=_batch("f6070809-1234-4abc-9def-040506070809", {
            "client_uuid": "f6070809-1234-4abc-9def-040506070809",
            "event_type": "anomaly_resolve",
            "target_type": "anomaly",
            "target_id": _ANOMALY_ID,
            "payload": {
                "anomaly_id": _ANOMALY_ID,
                "resolution_notes": "Porte sanglée, retour au dépôt prévu.",
            },
            "created_at_local": "2026-10-01T15:35:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "incident_create": OpenApiExample(
        "Signalement d'incident (incident_create)",
        value=_batch("07080910-5678-4abc-9def-050607080910", {
            "client_uuid": "07080910-5678-4abc-9def-050607080910",
            "event_type": "incident_create",
            "payload": {
                "title": "Bagage oublié à bord",
                # Facultatifs : défauts `other` / `low` si absents.
                "type": "luggage",
                "severity": "low",
                "description": "Sac à dos noir, bancs du milieu.",
                "trip_id": _TRIP_ID,
                "photos_urls": [
                    "https://media.toupac.sn/incidents/bagage-01.jpg",
                ],
                "gps_address": "Gare routière des Baux-Maraîchers, Dakar",
            },
            "created_at_local": "2026-10-01T16:10:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "activity_transition": OpenApiExample(
        "Transition d'état du voyage (activity_transition)",
        value=_batch("08091011-9abc-4def-9012-060708091011", {
            "client_uuid": "08091011-9abc-4def-9012-060708091011",
            "event_type": "activity_transition",
            "payload": {
                # Doit figurer dans Trip.Status et respecter le graphe des
                # transitions autorisées (cf. ALLOWED_TRANSITIONS).
                "to_status": "boarding",
                # Facultatif : si présent, DOIT correspondre au trip de la
                # session — sinon rejet TRIP_NOT_IN_SESSION.
                "trip_id": _TRIP_ID,
            },
            "created_at_local": "2026-10-01T13:50:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "parcel_verify": OpenApiExample(
        "Validation de colis à bord (parcel_verify)",
        value=_batch("09101112-cdef-4abc-9def-070809101112", {
            "client_uuid": "09101112-cdef-4abc-9def-070809101112",
            "event_type": "parcel_verify",
            "target_type": "parcel",
            "target_id": _PARCEL_ID,
            "payload": {
                "parcel_id": _PARCEL_ID,
            },
            "created_at_local": "2026-10-01T13:55:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
    "parcel_refuse": OpenApiExample(
        "Refus de colis non conforme (parcel_refuse)",
        value=_batch("10111213-ef01-4abc-9def-080910111213", {
            "client_uuid": "10111213-ef01-4abc-9def-080910111213",
            "event_type": "parcel_refuse",
            "target_type": "parcel",
            "target_id": _PARCEL_ID,
            "payload": {
                "parcel_id": _PARCEL_ID,
                "reason": "Emballage endommagé, contenu visible.",
            },
            "created_at_local": "2026-10-01T13:57:00+00:00",
            "gps_location": _DAKAR,
        }),
        request_only=True,
    ),
}

#: Deux verdicts suffisent pour montrer la forme du verdict enrichi : un
#: accepté avec `details`, un rejeté avec `rejection_code` + `anomaly`. Les
#: dupliquer par event_type ajouterait du bruit sans information nouvelle —
#: la structure du verdict ne dépend pas du type d'event.
RESPONSE_EXAMPLES = [
    OpenApiExample(
        "Vente à bord acceptée (verdict enrichi)",
        value={
            "session_id": _SESSION_ID,
            "processed": 1,
            "results": [
                {
                    "client_uuid": "c8f32d5b-0a4e-4f9c-b2d3-6e7f8091ab2c",
                    "status": "accepted",
                    "anomaly": None,
                    "details": {
                        "reservation_id": _RESERVATION_ID,
                        "passenger_id": _DRIVER_USER_ID,
                        "cash_entry_id": "0192f320-aaaa-7bbb-8ccc-dddddddddd01",
                        "reservation_status": "boarded",
                        "trip_status": "boarding",
                    },
                },
            ],
        },
        response_only=True,
    ),
    OpenApiExample(
        "Conflit de siège (rejet, anomalie conservée)",
        value={
            "session_id": _SESSION_ID,
            "processed": 1,
            "results": [
                {
                    "client_uuid": "c8f32d5b-0a4e-4f9c-b2d3-6e7f8091ab2c",
                    "status": "rejected",
                    "rejection_code": "SEAT_ALREADY_TAKEN",
                    "rejection_reason": "Siège A1 déjà occupé sur ce voyage.",
                    "anomaly": {
                        "id": _ANOMALY_ID,
                        "type": "seat_conflict",
                        "severity": "moderate",
                        "title": "Siège A1 déjà attribué — VYG-001",
                        "description": (
                            "Vente à bord refusée : le siège A1 du voyage "
                            "VYG-001 porte déjà une réservation active."
                        ),
                    },
                },
            ],
        },
        response_only=True,
    ),
]

#: Liste à passer à `@extend_schema(examples=...)`.
ALL_EXAMPLES = [*REQUEST_EXAMPLES.values(), *RESPONSE_EXAMPLES]
