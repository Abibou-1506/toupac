"""TOUPAC Notifications — Registry de resolvers et validation croisée (Ticket A)."""
import pytest

from notifications.catalog import all_events
from notifications.resolvers.base import (
    KNOWN_UNIMPLEMENTED_RESOLVERS,
    ResolvedRecipient,
    all_resolver_keys,
    get_resolver,
    register_resolver,
)

pytestmark = pytest.mark.django_db


def test_register_resolver_prevents_duplicates():
    key = "_test.duplicate_guard"

    @register_resolver(key)
    def _first(context, tenant):
        return []

    with pytest.raises(ValueError, match="already registered"):
        @register_resolver(key)
        def _second(context, tenant):
            return []


def test_get_resolver_returns_registered_function():
    @register_resolver("_test.roundtrip")
    def _resolve(context, tenant):
        return []

    assert get_resolver("_test.roundtrip") is _resolve


def test_get_resolver_raises_on_unknown_key():
    with pytest.raises(KeyError, match="No resolver registered"):
        get_resolver("_test.never_registered")


def test_example_customer_resolver_returns_user(tenant_a, user_admin_a):
    resolver = get_resolver("_example.customer_from_context")

    recipients = resolver({"user_id": str(user_admin_a.id)}, tenant_a)

    assert len(recipients) == 1
    assert recipients[0] == ResolvedRecipient(user=user_admin_a, trigger_scope="user")


def test_example_customer_resolver_ignores_user_from_other_tenant(tenant_a, user_admin_b):
    """Un destinataire d'un autre tenant ne doit jamais être résolu."""
    resolver = get_resolver("_example.customer_from_context")

    assert resolver({"user_id": str(user_admin_b.id)}, tenant_a) == []


def test_example_customer_resolver_returns_empty_without_user_id(tenant_a):
    resolver = get_resolver("_example.customer_from_context")

    assert resolver({}, tenant_a) == []


def test_example_role_resolver_returns_all_dispatchers(tenant_a, user_dispatcher_a, user_admin_a):
    """Scope 'role' : le broadcast ne retient que les porteurs du rôle."""
    from iam.models import User

    resolver = get_resolver("_example.dispatchers_of_tenant")
    recipients = resolver({}, tenant_a)

    assert [r.user for r in recipients] == [user_dispatcher_a]
    assert recipients[0].trigger_scope == "role"
    assert recipients[0].trigger_role == User.Role.DISPATCHER


def test_all_catalog_resolver_keys_are_known():
    """Aucune clé sauvage : chaque event pointe sur un resolver écrit ou déclaré à venir.

    Au Ticket E, implémenter un resolver impose de retirer sa clé de
    KNOWN_UNIMPLEMENTED_RESOLVERS — sans quoi ce test reste vert par accident.
    Le test suivant ferme cette porte.
    """
    known = all_resolver_keys() | KNOWN_UNIMPLEMENTED_RESOLVERS
    unknown = {e.resolver_key for e in all_events()} - known
    assert unknown == set(), f"resolver_key non déclarés : {sorted(unknown)}"


def test_unimplemented_list_does_not_contain_implemented_resolvers():
    """Filet inverse : une clé implémentée doit sortir de la liste 'à venir'."""
    stale = KNOWN_UNIMPLEMENTED_RESOLVERS & all_resolver_keys()
    assert stale == set(), f"resolvers implémentés encore listés comme à venir : {sorted(stale)}"


def test_unimplemented_list_has_no_orphan_keys():
    """Une clé listée 'à venir' que plus aucun event ne référence est du mort-bois."""
    referenced = {e.resolver_key for e in all_events()}
    orphans = KNOWN_UNIMPLEMENTED_RESOLVERS - referenced
    assert orphans == set(), f"clés orphelines dans KNOWN_UNIMPLEMENTED_RESOLVERS : {sorted(orphans)}"
