"""
TOUPAC Voyage — Étiquettes de sièges dérivées d'un plan.

Le même calcul vivait en deux endroits sans se ressembler : une fonction privée
du seed de démonstration, et `TripViewSet._build_seat_occupation`, qui seule
gérait le format explicite. La vente à bord en a désormais besoin pour refuser
un siège hors plan — un troisième exemplaire aurait garanti la divergence.

Trois formats de `SeatMap.layout` coexistent en base :

- **grille 2D V1.1** — `[[{"label": "A1"}, …, null, …], …]`. Chaque rangée est
  une liste de cellules (siège, conducteur, allée). C'est ce que produit
  l'éditeur visuel et ce que seedent les 5 templates système ;
- **explicite legacy** — `{"seats": [{"label": "A1", …}, …]}`, quand un plan
  pré-V1.1 était saisi siège par siège (rangées irrégulières, places
  condamnées, strapontins) ;
- **dérivé legacy** — `{"rows": N, "cols": M}`, qui suffit à un car régulier.

La 2D V1.1 prime, puis l'explicite, puis le dérivé. L'explicite prime sur le
dérivé : un plan qui énumère ses sièges le fait pour une raison, et recalculer
une grille par-dessus lui la contredirait.
"""


def _labels_from_grid(layout):
    """Extrait les labels des sièges d'un layout 2D V1.1.

    Parcourt rangée par rangée, cellule par cellule. Ignore les cellules None
    (allées) et les cellules conducteur (`type == "driver"` ou label "DRV").
    """
    labels = []
    for row in layout:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict):
                continue
            if cell.get("type") == "driver" or cell.get("label") == "DRV":
                continue
            label = cell.get("label")
            if label:
                labels.append(label)
    return labels


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
    if isinstance(layout, list):
        labels = _labels_from_grid(layout)
    else:
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
