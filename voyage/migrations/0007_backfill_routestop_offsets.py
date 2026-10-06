"""Backfill atomique des nouveaux arrival/departure offsets depuis l'ancien
`offset_minutes`. Une seule requête UPDATE via F() — O(1) sans boucle,
scale sur base de prod sans timeout.

Pattern DECISIONS.md « Data migration testable via `apps.get_model` ».
"""
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    RouteStop = apps.get_model("voyage", "RouteStop")
    RouteStop.objects.update(
        arrival_offset_minutes=F("offset_minutes"),
        departure_offset_minutes=F("offset_minutes"),
    )


def unbackfill(apps, schema_editor):
    # Pas de rollback nécessaire : les 2 nouveaux champs seront droppés par
    # le reverse de la migration schema 0006 si on fait un rollback complet.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("voyage", "0006_routestop_arrival_offset_minutes_and_more"),
    ]
    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
