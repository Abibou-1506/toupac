"""
TOUPAC Voyage — Signature et vérification des QR codes de billets.

RS256 dès qu'une paire de clés est configurée (settings.QR_JWT_PRIVATE_KEY /
QR_JWT_PUBLIC_KEY) : l'app contrôleur embarque alors la clé publique et vérifie
les billets hors réseau, sans jamais pouvoir en forger. À défaut — dev et
tests — repli sur HS256 avec SECRET_KEY, qui ne convient pas à la production
puisque le vérificateur peut aussi signer.
"""
import logging
from datetime import datetime, time, timedelta

import jwt
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _signing_config():
    """Retourne (clé, algorithme) pour la signature."""
    private_key = getattr(settings, "QR_JWT_PRIVATE_KEY", None)
    if private_key:
        return private_key, "RS256"
    return settings.SECRET_KEY, "HS256"


def _verification_config():
    """Retourne (clé, algorithme) pour la vérification."""
    public_key = getattr(settings, "QR_JWT_PUBLIC_KEY", None)
    if public_key:
        return public_key, "RS256"

    private_key = getattr(settings, "QR_JWT_PRIVATE_KEY", None)
    if private_key:
        # Clé publique non fournie : on la dérive de la clé privée.
        from cryptography.hazmat.primitives import serialization

        loaded = serialization.load_pem_private_key(
            private_key.encode() if isinstance(private_key, str) else private_key,
            password=None,
        )
        public_pem = loaded.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return public_pem, "RS256"

    return settings.SECRET_KEY, "HS256"


def qr_public_key_pem():
    """
    Clé publique PEM à embarquer dans le manifest, ou None.

    En HS256 il n'y a rien à distribuer : la clé de vérification est aussi la
    clé de signature, l'app ne doit surtout pas la recevoir.
    """
    key, algorithm = _verification_config()
    if algorithm != "RS256":
        return None
    return key.decode() if isinstance(key, bytes) else key


def _expiry_for(departure_date):
    """Fin du lendemain du départ — couvre les trajets de nuit qui arrivent au matin."""
    if departure_date is None:
        return timezone.now() + timedelta(days=1)
    naive = datetime.combine(departure_date + timedelta(days=1), time.max)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def sign_ticket_jwt(reservation):
    """Signe le billet d'une réservation et retourne le JWT à encoder en QR."""
    trip = reservation.trip
    issued_at = timezone.now()
    expires_at = _expiry_for(trip.departure_date)

    payload = {
        "reservation_id": str(reservation.id),
        "trip_id": str(trip.id),
        "tenant_id": str(reservation.tenant_id),
        "passenger_name": reservation.passenger.full_name,
        "seat_label": reservation.seat_label,
        "departure_date": trip.departure_date.isoformat() if trip.departure_date else None,
        "route_code": trip.route.code,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        # Claims standards : PyJWT contrôle l'expiration tout seul au décodage.
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    key, algorithm = _signing_config()
    return jwt.encode(payload, key, algorithm=algorithm)


def verify_ticket_jwt(token):
    """Retourne le payload du billet si le JWT est valide, None sinon."""
    try:
        key, algorithm = _verification_config()
        return jwt.decode(token, key, algorithms=[algorithm])
    except jwt.PyJWTError as exc:
        logger.info("Billet QR rejeté : %s", exc)
        return None
    # Catch large volontaire : clé mal configurée, PEM illisible...
    except Exception:
        logger.exception("Vérification du billet QR impossible")
        return None
