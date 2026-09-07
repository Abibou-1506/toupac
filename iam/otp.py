"""
TOUPAC IAM — Stockage et vérification des codes à usage unique (auth CLIENT).

Redis via le cache Django, TTL 5 minutes. Aucun modèle Django : un OTP n'a pas
de valeur d'audit qui justifierait sa persistance, et le TTL fait le ménage sans
tâche de maintenance. Le denylist JWT suit déjà ce parti.

Deux garde-fous portés ici :

- **Le code n'est jamais stocké en clair.** Seul son SHA-256 l'est, pour qu'une
  inspection accidentelle du dump Redis ne révèle pas les codes en circulation.
  Pas de sel : un code à six chiffres est de toute façon cassable par force
  brute hors ligne, le hachage protège contre la lecture, pas contre l'analyse —
  ce qui protège vraiment, c'est le TTL de 5 minutes et le plafond de tentatives.
- **Trois tentatives par challenge.** Au-delà, le challenge est détruit et
  l'utilisateur en redemande un neuf. Sans cela, six chiffres se devinent en un
  million de requêtes.

Ce module ne contient aucune logique métier : ni résolution d'utilisateur, ni
envoi de notification. Il ne sait que créer, vérifier et masquer.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

OTP_KEY_PREFIX = "otp:"
OTP_TTL_SECONDS = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 3

#: Codes d'erreur rendus par `verify_challenge`. Stables, contrairement aux
#: messages affichés — les tests et les clients s'appuient dessus.
ERROR_NOT_FOUND = "not_found"
ERROR_EXPIRED = "expired"
ERROR_TOO_MANY_ATTEMPTS = "too_many_attempts"
ERROR_WRONG_CODE = "wrong_code"


def _challenge_key(challenge_id):
    return f"{OTP_KEY_PREFIX}{challenge_id}"


def _hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()


def generate_code():
    """Six chiffres, tirés par `secrets` — jamais par `random`."""
    return f"{secrets.randbelow(1_000_000):06d}"


def create_challenge(user_id, target_type, target):
    """
    Crée un challenge OTP. Retourne `(challenge_id, code_en_clair)`.

    Le code en clair n'est retourné qu'ici : il part vers le canal choisi et
    n'est jamais relu depuis le stockage.
    """
    challenge_id = str(uuid.uuid4())
    code = generate_code()
    payload = {
        "user_id": str(user_id),
        "code_hash": _hash_code(code),
        "target_type": target_type,
        "target": target,
        "expires_at": (timezone.now() + timedelta(seconds=OTP_TTL_SECONDS)).isoformat(),
        "attempts": 0,
    }
    cache.set(_challenge_key(challenge_id), payload, timeout=OTP_TTL_SECONDS)
    return challenge_id, code


def _remaining_seconds(payload):
    """Secondes restantes d'après l'échéance stockée dans le payload.

    Le backend de cache est `django.core.cache.backends.redis.RedisCache`, qui
    n'expose pas le TTL d'une clé — seul `django-redis`, qui n'est pas installé
    ici, le ferait. Plutôt que d'atteindre le client redis-py par une API
    privée, l'échéance absolue est écrite dans le payload à la création : la
    réécriture après un échec conserve ainsi la fenêtre d'origine au lieu de la
    rallonger à chaque tentative.
    """
    expires_at = datetime.fromisoformat(payload["expires_at"])
    return int((expires_at - timezone.now()).total_seconds())


def verify_challenge(challenge_id, submitted_code):
    """
    Vérifie un code contre un challenge.

    Retourne `(user_id, error)` : `user_id` en cas de succès, sinon l'un des
    codes `ERROR_*`. Le challenge est consommé dès qu'il aboutit — un code
    valide ne sert qu'une fois.
    """
    key = _challenge_key(challenge_id)
    payload = cache.get(key)
    if payload is None:
        # Purge par TTL, identifiant inventé ou challenge déjà consommé : les
        # trois se confondent volontairement, distinguer renseignerait un
        # attaquant sur l'existence d'un challenge.
        return None, ERROR_NOT_FOUND

    remaining = _remaining_seconds(payload)
    if remaining <= 0:
        cache.delete(key)
        return None, ERROR_EXPIRED

    if payload["attempts"] >= OTP_MAX_ATTEMPTS:
        cache.delete(key)
        return None, ERROR_TOO_MANY_ATTEMPTS

    if not secrets.compare_digest(_hash_code(submitted_code), payload["code_hash"]):
        payload["attempts"] += 1
        if payload["attempts"] >= OTP_MAX_ATTEMPTS:
            cache.delete(key)
            return None, ERROR_TOO_MANY_ATTEMPTS
        cache.set(key, payload, timeout=remaining)
        return None, ERROR_WRONG_CODE

    cache.delete(key)
    return payload["user_id"], None


def peek_challenge(challenge_id):
    """Payload brut du challenge, ou None. Réservé aux tests et au diagnostic."""
    return cache.get(_challenge_key(challenge_id))


def mask_target(target_type, target):
    """
    Rend une cible affichable sans la divulguer : « +2217****67 », « fa***@ex.com ».

    Le masque doit rester lisible sur des valeurs courtes sans jamais lever ni
    rendre la valeur en clair : une cible trop courte pour être masquée
    utilement est remplacée par des étoiles plutôt que renvoyée telle quelle.
    """
    if not target:
        return ""

    if target_type == "phone":
        if len(target) <= 7:
            return "*" * len(target)
        return f"{target[:5]}****{target[-2:]}"

    if target_type == "email":
        local, separator, domain = target.partition("@")
        if not separator:
            # Pas une adresse : on ne devine pas, on masque tout.
            return "*" * len(target)
        if len(local) <= 2:
            return f"{'*' * len(local)}@{domain}"
        return f"{local[:2]}***@{domain}"

    return "*" * len(target)
