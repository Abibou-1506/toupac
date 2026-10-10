"""Ajoute `SeatMap.code` + backfill des plans existants.

Préparation Phase 7 backoffice web : la colonne `code` est affichée dans
SeatMaps.jsx (chip "BUS-45", "MINI-15"...). Le save() du modèle le génère
pour toute nouvelle instance ; cette migration pose le champ et comble
les lignes déjà en base, templates système inclus.

Pattern DECISIONS.md « Data migration testable via `apps.get_model` ».
"""
from django.db import migrations, models


def backfill_code(apps, schema_editor):
    SeatMap = apps.get_model("voyage", "SeatMap")
    for seat_map in SeatMap.objects.all().iterator():
        if seat_map.code:
            continue
        if seat_map.vehicle_type_id:
            vt = seat_map.vehicle_type
            raw = (vt.name[:4]).upper().strip() if vt and vt.name else ""
            prefix = raw or "PLAN"
            seat_map.code = f"{prefix}-{seat_map.total_seats}"
        else:
            seat_map.code = f"PLAN-{seat_map.total_seats}"
        seat_map.save(update_fields=["code"])


def reverse_noop(apps, schema_editor):
    # Vide volontairement : rollback de la colonne suffit, pas de perte
    # métier à craindre (code purement dérivé).
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("voyage", "0007_backfill_routestop_offsets"),
    ]

    operations = [
        migrations.AddField(
            model_name="seatmap",
            name="code",
            field=models.CharField(
                blank=True, db_index=True, max_length=32, verbose_name="Code",
                help_text=(
                    "Code court auto-généré au save pour affichage DS "
                    "(ex. BUS-45, MINI-15, PLAN-45). Idempotent — ne régénère "
                    "pas si déjà posé."
                ),
            ),
        ),
        migrations.RunPython(backfill_code, reverse_noop),
    ]
