"""Base des resolvers de destinataires — un resolver mappe un événement et son
contexte à une liste concrète d'utilisateurs à notifier.

Une `Notification` vise UN utilisateur. Un événement diffusé à un rôle (ex:
DSP-03 pour tous les dispatchers) produit donc N notifications individuelles :
le resolver retourne les N users, le service (Ticket B) crée les N lignes. C'est
ce qui rend `read_at` / `acked_at` naturellement par-utilisateur.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations seulement
    from iam.models import Tenant, User


@dataclass(frozen=True)
class ResolvedRecipient:
    user: User
    trigger_scope: str   # "user" | "role" | "tenant"
    trigger_role: str = ""


ResolverFunc = Callable[[dict, "Tenant"], list[ResolvedRecipient]]


_RESOLVERS: dict[str, ResolverFunc] = {}


def register_resolver(key: str):
    """Décorateur : @register_resolver('payment.customer') def _resolve(context, tenant): ..."""
    def _wrap(func: ResolverFunc) -> ResolverFunc:
        if key in _RESOLVERS:
            raise ValueError(f"Resolver already registered: {key}")
        _RESOLVERS[key] = func
        return func
    return _wrap


def get_resolver(key: str) -> ResolverFunc:
    if key not in _RESOLVERS:
        raise KeyError(f"No resolver registered for '{key}'")
    return _RESOLVERS[key]


def all_resolver_keys() -> set[str]:
    return set(_RESOLVERS.keys())


#: Resolvers référencés par le catalogue mais pas encore écrits.
#:
#: **Vide depuis le câblage métier (Ticket E1E2)** : les 29 clés de la matrice
#: TOUPAC ONE sont implémentées. La liste reste, et doit le rester : c'est elle
#: qui permet de déclarer un événement dont le resolver viendra plus tard sans
#: que `test_resolvers.py` ne refuse la clé. Y inscrire une clé est un aveu
#: daté, pas une échappatoire — l'invariant croisé interdit toujours d'inventer
#: une clé sauvage comme d'oublier d'en implémenter une en silence.
KNOWN_UNIMPLEMENTED_RESOLVERS = frozenset()
