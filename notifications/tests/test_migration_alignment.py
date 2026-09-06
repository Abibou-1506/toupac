"""TOUPAC Notifications — Invariants de la data migration 0005 (Ticket A).

Ces tests portent sur les tables de correspondance, pas sur l'exécution de
`forward()`. Raison : la migration retire `subject` dans le même fichier que le
backfill, donc le modèle historique dont `forward()` a besoin ne correspond plus
au schéma en base une fois la migration passée — la rejouer via `apps.get_model`
sur la base de test échouerait sur une colonne absente. Le chemin RunPython
lui-même a été vérifié à la main sur la base de dev (7 gabarits → 5, les deux
collisions tranchées, `subject` recopié).

Ce que ces tests attrapent quand même, et qui casserait en production : un code
canonique mal orthographié dans la migration (donc absent du catalogue), ou un
gagnant de collision qui ne serait pas lui-même un code hérité.
"""
import importlib

from notifications.catalog import all_events

# Le nom du module commence par un chiffre : import direct impossible.
_migration = importlib.import_module(
    "notifications.migrations.0005_backfill_templates_and_seed_alignment"
)
LEGACY_TO_CANONICAL = _migration.LEGACY_TO_CANONICAL
COLLISION_WINNERS = _migration.COLLISION_WINNERS


def test_every_canonical_target_is_a_registered_event():
    """Un code cible absent du catalogue = gabarit muet, jamais retrouvé à l'envoi."""
    registered = {e.code for e in all_events()}
    unknown = set(LEGACY_TO_CANONICAL.values()) - registered
    assert unknown == set(), f"codes canoniques inconnus du catalogue : {sorted(unknown)}"


def test_collision_winners_are_legacy_codes_mapping_to_their_target():
    for canonical, winner in COLLISION_WINNERS.items():
        assert winner in LEGACY_TO_CANONICAL, f"gagnant '{winner}' absent du mapping"
        assert LEGACY_TO_CANONICAL[winner] == canonical


def test_every_ambiguous_target_declares_a_winner():
    """Deux codes hérités vers une même cible sans arbitre = violation d'unicité."""
    targets = {}
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        targets.setdefault(canonical, []).append(legacy)

    ambiguous = {code for code, legacies in targets.items() if len(legacies) > 1}
    assert ambiguous == set(COLLISION_WINNERS), (
        f"cibles ambiguës sans arbitre : {sorted(ambiguous - set(COLLISION_WINNERS))}"
    )
