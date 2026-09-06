"""TOUPAC Notifications — Catégories de préférences et champ User (N-02, Ticket A).

La sémantique « clé absente = opt-in » et le filet NEVER_OPT_OUT sont appliqués
par le service au Ticket B ; ici on ne verrouille que le contrat de données.
"""
import pytest

from notifications.catalog import all_events
from notifications.preferences import ALL_CATEGORIES, NEVER_OPT_OUT

pytestmark = pytest.mark.django_db


def test_never_opt_out_is_a_subset_of_all_categories():
    assert NEVER_OPT_OUT <= ALL_CATEGORIES


def test_every_declared_category_is_used_by_at_least_one_event():
    """Une catégorie sans event est du mort-bois que les prefs exposeraient pour rien."""
    used = {e.category for e in all_events()}
    assert ALL_CATEGORIES - used == set()


def test_user_notification_preferences_defaults_to_empty_dict(user_admin_a):
    user_admin_a.refresh_from_db()
    assert user_admin_a.notification_preferences == {}


def test_user_notification_preferences_roundtrips_a_dict(user_admin_a):
    user_admin_a.notification_preferences = {"marketing": False, "trip_updates": True}
    user_admin_a.save(update_fields=["notification_preferences"])

    user_admin_a.refresh_from_db()
    assert user_admin_a.notification_preferences == {"marketing": False, "trip_updates": True}
