"""
TOUPAC Voyage — Signature et vérification des QR codes de billets.

RS256 exclusivement (asymétrique) : l'app contrôleur embarque la clé publique
et vérifie les billets hors réseau, sans jamais pouvoir en forger — un secret
partagé (HS256) exigerait de diffuser la clé de signature à chaque device
contrôleur, ce qui transforme le vol d'un seul appareil en compromission
systémique. Cutover strict : les JWT HS256 émis avant cette bascule ne sont
plus vérifiables, il n'y a pas de mode hybride.

Résolution des clés :
- Privée : settings.TOUPAC_QR_PRIVATE_KEY_PEM (env). Absente ⇒ keypair
  éphémère générée en mémoire au premier appel, avec un warning fort — ça ne
  doit jamais bloquer un `runserver` local, mais ça ne doit pas non plus
  passer inaperçu (les billets ne survivent pas à un redémarrage du process).
- Publique : dérivée de la clé qui signe RÉELLEMENT dans ce process — la clé
  configurée si présente, sinon la keypair éphémère UNE FOIS générée. Ce
  module signe et vérifie dans le même process ; exposer une clé publique qui
  ne correspond pas à la clé de signature active produirait des billets que
  ni ce process ni l'app mobile ne pourraient jamais vérifier. Seulement en
  l'absence de toute clé privée (process de vérification pur, qui ne signe
  jamais) on retombe sur settings.TOUPAC_QR_PUBLIC_KEY_PEM, puis sur le
  fichier committé voyage/keys/qr_public.pem, puis sur None.
"""
import logging
import threading
from datetime import timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
_EPHEMERAL_KEY_SIZE_BITS = 2048
_COMMITTED_PUBLIC_KEY_PATH = Path(__file__).resolve().parent.parent / "keys" / "qr_public.pem"

# La keypair éphémère est générée une seule fois par process, pas à chaque
# appel — sinon un billet signé à l'instant T ne serait déjà plus vérifiable
# à T+1 dans le même process.
_ephemeral_lock = threading.Lock()
_ephemeral_private_pem = None
_ephemeral_public_pem = None


def _get_ephemeral_keypair():
    """Keypair de secours pour le dev — jamais persistée sur disque."""
    global _ephemeral_private_pem, _ephemeral_public_pem
    with _ephemeral_lock:
        if _ephemeral_private_pem is None:
            logger.warning(
                "TOUPAC_QR_PRIVATE_KEY_PEM absente : génération d'une keypair RS256 "
                "ÉPHÉMÈRE en mémoire. Les billets signés ne seront plus vérifiables "
                "après un redémarrage du process. À ne JAMAIS utiliser en production "
                "— configurer TOUPAC_QR_PRIVATE_KEY_PEM."
            )
            key = rsa.generate_private_key(public_exponent=65537, key_size=_EPHEMERAL_KEY_SIZE_BITS)
            _ephemeral_private_pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            _ephemeral_public_pem = key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        return _ephemeral_private_pem, _ephemeral_public_pem


def _configured_private_key():
    """Clé privée depuis l'env, ou None si absente."""
    private_key = getattr(settings, "TOUPAC_QR_PRIVATE_KEY_PEM", "") or None
    return private_key.encode() if isinstance(private_key, str) else private_key


def _signing_key():
    """Clé privée PEM (bytes) utilisée pour signer — configurée ou éphémère."""
    configured = _configured_private_key()
    if configured:
        return configured
    ephemeral_private, _ = _get_ephemeral_keypair()
    return ephemeral_private


def _verification_key():
    """
    Clé publique PEM (bytes) utilisée pour vérifier, ou None.

    Priorité à la clé qui signe réellement dans CE process :
    1. Dérivée de TOUPAC_QR_PRIVATE_KEY_PEM si configurée (ou l'env public,
       si l'opérateur l'a fournie explicitement — les deux sont censés
       correspondre, c'est la paire qu'il a générée ensemble).
    2. Keypair éphémère de ce process, SEULEMENT si déjà générée — on ne la
       force pas ici : c'est `sign_ticket_jwt` qui décide quand en créer une.
    3. Env public seul / fichier committé — pertinent uniquement pour un
       process qui ne signe jamais (pur vérificateur), sinon ces valeurs
       risqueraient de ne pas correspondre à la clé éphémère qui finira par
       signer.
    4. None.
    """
    configured_private = _configured_private_key()
    if configured_private:
        explicit_public = getattr(settings, "TOUPAC_QR_PUBLIC_KEY_PEM", "") or None
        if explicit_public:
            return explicit_public.encode() if isinstance(explicit_public, str) else explicit_public
        loaded = serialization.load_pem_private_key(configured_private, password=None)
        return loaded.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    if _ephemeral_public_pem is not None:
        return _ephemeral_public_pem

    public_key = getattr(settings, "TOUPAC_QR_PUBLIC_KEY_PEM", "") or None
    if public_key:
        return public_key.encode() if isinstance(public_key, str) else public_key

    if _COMMITTED_PUBLIC_KEY_PATH.exists():
        return _COMMITTED_PUBLIC_KEY_PATH.read_bytes()

    return None


def qr_public_key_pem():
    """Clé publique PEM (str) à distribuer — manifest et endpoint dédié. None si indisponible."""
    key = _verification_key()
    if key is None:
        logger.warning(
            "Aucune clé publique QR disponible (ni TOUPAC_QR_PUBLIC_KEY_PEM, ni "
            "voyage/keys/qr_public.pem, ni clé privée dont dériver). Le manifest "
            "exposera qr_public_key: null — l'app mobile ne pourra pas vérifier "
            "les billets hors ligne."
        )
        return None
    return key.decode() if isinstance(key, bytes) else key


def _expiry_for(scheduled_at):
    """scheduled_at + 24h — couvre les trajets de nuit et les retards raisonnables."""
    if scheduled_at is None:
        return timezone.now() + timedelta(hours=24)
    return scheduled_at + timedelta(hours=24)


def sign_ticket_jwt(reservation):
    """Signe le billet d'une réservation en RS256 et retourne le JWT à encoder en QR."""
    trip = reservation.trip
    issued_at = timezone.now()
    expires_at = _expiry_for(trip.scheduled_at if trip else None)

    payload = {
        "sub": str(reservation.id),
        "trip": str(reservation.trip_id),
        "seat": reservation.seat_label,
        "pax": reservation.passenger.full_name if reservation.passenger else "",
        "tenant": str(reservation.tenant_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def verify_ticket_jwt(token):
    """
    Vérifie un JWT RS256 et retourne son payload, ou None si invalide/expiré.

    Cutover strict : un JWT signé en HS256 (avant cette bascule) est rejeté
    au même titre qu'un token forgé — `algorithms=[ALGORITHM]` fait échouer
    PyJWT sur toute valeur d'`alg` autre que RS256, il n'y a pas de repli.
    """
    key = _verification_key()
    if key is None:
        logger.error("Vérification de billet impossible : aucune clé publique QR configurée.")
        return None
    try:
        return jwt.decode(token, key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.info("Billet QR rejeté : %s", exc)
        return None
    # Catch large volontaire : PEM illisible, clé mal formée...
    except Exception:
        logger.exception("Vérification du billet QR impossible")
        return None
