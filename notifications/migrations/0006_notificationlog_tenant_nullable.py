"""Rend le tenant facultatif sur le journal d'envoi.

Une notification de plateforme n'appartient à aucune compagnie. Le cas type est
le code de connexion d'un client TOUPAC : depuis USR-1, le client est global, il
n'a pas de compagnie au moment où il se connecte. Journaliser cet envoi levait
une IntegrityError, ce qui faisait échouer la demande de code elle-même.

Aligné sur `iam.AuditLog.tenant` et `NotificationTemplate.tenant`, nullables
depuis l'origine pour la même raison.

Réversible tant qu'aucune ligne sans tenant n'a été écrite ; le retour arrière
échouerait sinon, ce qui est le bon signal.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('iam', '0010_user_staff_email_constraint'),
        ('notifications', '0005_backfill_templates_and_seed_alignment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationlog',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifications_notificationlog_set', to='iam.tenant', verbose_name='Tenant'),
        ),
    ]
