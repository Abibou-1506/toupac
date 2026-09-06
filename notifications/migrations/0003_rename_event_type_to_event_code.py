"""Renomme event_type → event_code (convention notif.{domaine}.{evenement}.{version}).

Écrite à la main plutôt qu'auto-générée : le questionneur de makemigrations
n'est pas utilisable en non-interactif, et un « non » à la question « avez-vous
renommé ? » produirait RemoveField + AddField, donc la perte de tous les
event_type existants. RenameField préserve la colonne et ses données.

La contrainte unique référence le champ : elle est retirée avant le rename et
recréée après, sinon PostgreSQL refuse le renommage de la colonne portée.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_alter_notificationtemplate_channel"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="notificationtemplate",
            name="unique_template_per_tenant_event_channel_lang",
        ),
        migrations.RenameField(
            model_name="notificationtemplate",
            old_name="event_type",
            new_name="event_code",
        ),
        migrations.RenameField(
            model_name="notificationlog",
            old_name="event_type",
            new_name="event_code",
        ),
        migrations.AlterField(
            model_name="notificationtemplate",
            name="event_code",
            field=models.CharField(max_length=50, verbose_name="Code d'événement"),
        ),
        migrations.AlterField(
            model_name="notificationlog",
            name="event_code",
            field=models.CharField(max_length=50, verbose_name="Code d'événement"),
        ),
        migrations.AddConstraint(
            model_name="notificationtemplate",
            constraint=models.UniqueConstraint(
                fields=("tenant", "event_code", "channel", "language"),
                name="unique_template_per_tenant_event_channel_lang",
            ),
        ),
    ]
