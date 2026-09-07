"""
TOUPAC Notifications — Idempotence des émissions (N-06).

Deux filets, à deux endroits, pour deux problèmes distincts :

- **Redis**, consulté avant tout travail. Il attrape le cas courant : un même
  événement ré-émis parce qu'une tâche a été rejouée, qu'un utilisateur a
  double-cliqué, qu'un webhook est arrivé deux fois. Court-circuit immédiat,
  aucune requête en base.
- **La contrainte unique en base** (posée au Ticket A), qui attrape ce que Redis
  laisse passer : deux workers Celery entrant dans la fenêtre au même instant.
  Redis ne sérialise pas — entre le `get` et le `set`, l'autre worker est déjà
  parti. La base, elle, tranche.

Le premier évite du travail, le second garantit l'unicité. L'un sans l'autre
laisserait soit des doublons sous charge, soit une base sollicitée pour rien.

La clé ne dépend jamais des destinataires résolus : on l'évalue avant la
résolution, précisément pour ne pas la payer quand l'émission est un doublon.
"""
import hashlib
import json

from django.core.cache import cache

#: Préfixe des clés Redis. Distinct de tout autre usage du cache.
IDEMPOTENCY_KEY_PREFIX = "notif_idem:"

#: Une journée : au-delà, ré-émettre le même événement est un acte volontaire
#: (relance manuelle, rattrapage), pas un doublon accidentel.
IDEMPOTENCY_TTL_SECONDS = 86_400

#: Longueur retenue de l'empreinte. 32 caractères hexadécimaux = 128 bits, très
#: au-delà de ce qu'il faut pour éviter une collision, et la colonne
#: `Notification.idempotency_key` est dimensionnée à 100.
_DIGEST_LENGTH = 32


def compute_idempotency_key(event_code, actor_id=None, scope=None, context=None):
    """
    Empreinte déterministe de l'émission.

    Le contexte est sérialisé en JSON trié : deux dictionnaires équivalents mais
    construits dans un ordre différent donnent la même clé. `default=str`
    convertit ce que JSON ignore — dates, UUID, décimaux — plutôt que d'échouer,
    au prix d'une hypothèse assumée : deux valeurs dont la représentation
    textuelle coïncide sont tenues pour identiques.
    """
    canonical_context = json.dumps(context or {}, sort_keys=True, default=str, ensure_ascii=False)
    material = f"{event_code}:{actor_id or ''}:{scope or ''}:{canonical_context}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def _cache_key(idempotency_key):
    return f"{IDEMPOTENCY_KEY_PREFIX}{idempotency_key}"


def already_emitted(idempotency_key):
    """Cette émission a-t-elle déjà eu lieu dans la fenêtre courante ?"""
    return cache.get(_cache_key(idempotency_key)) is not None


def mark_emitted(idempotency_key):
    """
    Marque l'émission comme faite.

    Posée seulement après un succès partiel au moins : si tout a échoué, laisser
    la clé absente permet à l'appelant de retenter sans attendre la journée.
    """
    cache.set(_cache_key(idempotency_key), "1", timeout=IDEMPOTENCY_TTL_SECONDS)


def forget(idempotency_key):
    """Retire la marque. Réservé aux tests et au rattrapage manuel."""
    cache.delete(_cache_key(idempotency_key))
