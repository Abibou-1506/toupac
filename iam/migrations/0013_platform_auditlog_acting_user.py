"""Ajoute au journal d'audit le client au nom duquel l'appel a été fait.

Sans cette colonne, la trace dit « le partenaire a lu des réservations chez
Sahel Express » sans dire celles de qui — inexploitable en cas d'incident, et
insuffisant pour répondre à un client qui demande qui a consulté ses données.

Nullable : les endpoints globaux (liste des compagnies, santé de la clé)
n'agissent pour personne, et les appels refusés avant résolution non plus.

`SET_NULL` plutôt que `CASCADE` : la suppression d'un compte client ne doit pas
effacer la trace des accès dont il a fait l'objet.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0012_platform_credential_flexibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformauditlog",
            name="acting_user",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="platform_audit_logs_as_acting",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Client représenté",
                help_text="Client au nom duquel la requête a été faite "
                          "(X-Acting-User-Email). Vide pour les endpoints globaux, "
                          "qui n'agissent pour personne.",
            ),
        ),
    ]
