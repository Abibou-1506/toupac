"""Normalise is_staff=False pour tous les DRIVER existants.

Depuis Ticket 4 Gamma, DRIVER n'accède pas à /admin/ : son outil est le
mobile. Les DRIVER créés avant Ticket 4 avec is_staff=True par erreur
sont normalisés à False ici. Zéro effet si aucun DRIVER is_staff=True
n'existe en base.
"""
from django.db import migrations


def normalize_driver_is_staff(apps, schema_editor):
    User = apps.get_model("iam", "User")
    User.objects.filter(role="driver", is_staff=True).update(is_staff=False)


def noop_reverse(apps, schema_editor):
    """Pas de rollback automatisé : si on avait créé des DRIVER is_staff=True
    par erreur, les restaurer serait réintroduire l'erreur. Un rollback de ce
    ticket passe par la non-application de la migration, pas par son inverse.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("iam", "0013_platform_auditlog_acting_user"),
    ]

    operations = [
        migrations.RunPython(normalize_driver_is_staff, noop_reverse),
    ]
