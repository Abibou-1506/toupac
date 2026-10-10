"""Formatage FR partagé pour serializers voyage."""

_DAY_SETS = {
    frozenset([1, 2, 3, 4, 5]): "Lun-Ven",
    frozenset([6, 7]): "Weekend",
    frozenset([1, 2, 3, 4, 5, 6, 7]): "Tous les jours",
}
_DAY_LABELS = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Jeu", 5: "Ven", 6: "Sam", 7: "Dim"}


def days_label_fr(days):
    """Transforme une liste d'entiers 1-7 (lundi=1) en libellé FR."""
    s = frozenset(days or [])
    if not s:
        return ""
    if s in _DAY_SETS:
        return _DAY_SETS[s]
    return ", ".join(_DAY_LABELS[d] for d in sorted(s) if d in _DAY_LABELS)
