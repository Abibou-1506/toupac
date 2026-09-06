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


#: Resolvers référencés par le catalogue mais pas encore écrits — ils seront
#: implémentés un par un au Ticket E (câblage métier), et chaque implémentation
#: RETIRE sa clé de cette liste. `test_resolvers.py` refuse toute clé de
#: catalogue qui ne serait ni implémentée ni listée ici : impossible d'inventer
#: une clé sauvage, impossible d'oublier d'en implémenter une en silence.
KNOWN_UNIMPLEMENTED_RESOLVERS = frozenset({
    "auth.self",
    "auth.self_and_admins",
    "order.customer",
    "order.customer_and_agent",
    "payment.customer",
    "payment.customer_and_finance",
    "ticket.customer",
    "trip.customer_and_driver",
    "trip.all_stakeholders",
    "trip.customer_and_station",
    "dispatch.driver",
    "dispatch.dispatcher",
    "control.controller_and_supervisor",
    "parcel.sender_and_recipient",
    "parcel.sender",
    "parcel.recipient",
    "incident.dispatchers_and_admin",
    "incident.reporter_and_impacted",
    "gps.dispatchers_and_fleet",
    "gps.dispatchers_and_it",
    "fleet.manager_and_mechanic",
    "compliance.responsible_and_driver",
    "finance.finance_and_station",
    "approval.approver",
    "stock.warehouse_and_purchase",
    "crm.customer_and_agent",
    "marketing.consented_customers",
    "bi.direction_and_finance",
    "si.admins_and_support",
})
