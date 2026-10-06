"""Insertion des 5 templates système SeatMap (V1.1).

Noms, dimensions et layouts conformes au mockup DS (SeatMaps.jsx > SME_TEMPLATES).
Les labels des sièges sont générés via la logique `smeAutoLabel` reproduite ici
en Python natif (lettre = position dans la rangée, chiffre = numéro de rangée
avec sièges) — pré-calculés pour garder la migration simple et traçable.

Les 5 templates :
- Vierge        : grille 6×10 vide (0 sièges)
- 45 places classique : D (conducteur) + 10 rangées 2+allée+2 + banquette 5 → 45 sièges
- 30 places classique : D + guide 1 siège + 6 rangées 2+allée+2 + banquette 5 → 30 sièges
- Minibus 15    : D + 5 rangées 1+allée+2 → 15 sièges
- Van 20        : D + 5 rangées 2+allée+2 → 20 sièges
"""
from django.db import migrations


SME_LETTERS = "ABCDEFGHIJKLMNOP"


def _auto_label(grid):
    """Reproduit la logique `smeAutoLabel` du mockup DS (SeatMaps.jsx)."""
    out = []
    row_no = 0
    for row in grid:
        has_seat = any(c and c.get("t") == "seat" for c in row)
        if has_seat:
            row_no += 1
        new_row = []
        k = 0
        for cell in row:
            if cell is None or cell.get("t") != "seat":
                new_row.append(cell)
                continue
            label = f"{SME_LETTERS[k]}{row_no}"
            k += 1
            new_row.append({"t": "seat", "label": label})
        out.append(new_row)
    return out


def _parse_row(spec):
    """`'xx.xx'` → liste de cellules éditeur (`{t:seat}` / `{t:drv}` / None)."""
    cells = []
    for ch in spec:
        if ch == "x":
            cells.append({"t": "seat", "label": ""})
        elif ch == "D":
            cells.append({"t": "drv"})
        elif ch == ".":
            cells.append(None)
        else:
            raise ValueError(f"Caractère de template inattendu : {ch!r}")
    return cells


def _to_api_layout(grid):
    """Converti la grille éditeur en layout API (`{label, type?}` ou None)."""
    out = []
    for row in grid:
        new_row = []
        for cell in row:
            if cell is None:
                new_row.append(None)
            elif cell.get("t") == "drv":
                new_row.append({"label": "DRV", "type": "driver"})
            else:
                new_row.append({"label": cell["label"]})
        out.append(new_row)
    return out


def _build(rows_spec):
    """Construit un layout API à partir d'une liste de specs compactes."""
    editor_grid = [_parse_row(row) for row in rows_spec]
    labeled = _auto_label(editor_grid)
    return _to_api_layout(labeled)


def _count_seats(layout):
    """Compte les cellules de type `seat` (hors driver, hors None)."""
    return sum(
        1
        for row in layout
        for cell in row
        if cell is not None and cell.get("type") != "driver"
    )


TEMPLATES = [
    {
        "name": "Vierge",
        "layout": _build(["......"] * 10),
    },
    {
        "name": "45 places classique",
        "layout": _build(["D...."] + ["xx.xx"] * 10 + ["xxxxx"]),
    },
    {
        "name": "30 places classique",
        "layout": _build(["D...x"] + ["xx.xx"] * 6 + ["xxxxx"]),
    },
    {
        "name": "Minibus 15",
        "layout": _build(["D..."] + ["x.xx"] * 5),
    },
    {
        "name": "Van 20",
        "layout": _build(["D...."] + ["xx.xx"] * 5),
    },
]


def seed_templates(apps, schema_editor):
    SeatMap = apps.get_model("voyage", "SeatMap")
    for tpl in TEMPLATES:
        layout = tpl["layout"]
        SeatMap.objects.update_or_create(
            name=tpl["name"],
            tenant=None,
            is_template=True,
            defaults={
                "layout": layout,
                "total_seats": _count_seats(layout),
            },
        )


def unseed_templates(apps, schema_editor):
    SeatMap = apps.get_model("voyage", "SeatMap")
    SeatMap.objects.filter(
        tenant__isnull=True,
        is_template=True,
        name__in=[tpl["name"] for tpl in TEMPLATES],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("voyage", "0004_seatmap_is_template_alter_seatmap_tenant"),
    ]
    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
