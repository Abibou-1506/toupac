"""
TOUPAC Voyage — Étiquettes de sièges dérivées d'un plan.

Le même calcul vivait en deux endroits sans se ressembler : une fonction privée
du seed de démonstration, et `TripViewSet._build_seat_occupation`, qui seule
gérait le format explicite. La vente à bord en a désormais besoin pour refuser
un siège hors plan — un troisième exemplaire aurait garanti la divergence.

Deux formats de `SeatMap.layout` coexistent en base :

- **explicite** — `{"seats": [{"label": "A1", …}, …]}`, quand le plan est saisi
  siège par siège (rangées irrégulières, places condamnées, strapontins) ;
- **dérivé** — `{"rows": N, "cols": M}`, qui suffit à un car régulier.

L'explicite prime : un plan qui énumère ses sièges le fait pour une raison, et
recalculer une grille par-dessus lui la contredirait.
"""


def seat_labels(layout, total_seats=None):
    """
    Étiquettes du plan, dans l'ordre d'affichage (A1, B1, … puis A2, B2, …).

    `total_seats` tronque la liste — un plan de grille rend `rows x cols`
    étiquettes, dont les dernières peuvent dépasser la capacité réelle du
    véhicule. Omettre l'argument rend le plan entier.

    Rend une liste vide quand aucun plan n'est exploitable, ce que l'appelant
    doit traiter comme « pas de plan déclaré » et non comme « plan vide » : un
    voyage sans `seat_map` est une configuration légitime.
    """
    layout = layout or {}

    explicit = layout.get("seats") or []
    if explicit:
        labels = [
            seat["label"] for seat in explicit
            if isinstance(seat, dict) and seat.get("label")
        ]
    else:
        rows = layout.get("rows") or 0
        cols = layout.get("cols") or 0
        labels = [
            f"{chr(64 + col)}{row}"
            for row in range(1, rows + 1)
            for col in range(1, cols + 1)
        ]

    return labels[:total_seats] if total_seats else labels


def trip_seat_labels(trip):
    """Étiquettes du plan d'un voyage. Liste vide si aucun plan n'est rattaché."""
    if trip.seat_map_id is None:
        return []
    return seat_labels(trip.seat_map.layout, trip.total_seats)
