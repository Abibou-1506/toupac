"""Le personnel doit avoir un e-mail : c'est sa seule voie de connexion.

Le client en est dispensé — il se connecte par code, sur e-mail ou téléphone.
Le compte de service aussi : ses comptes ne se connectent jamais.

Aucune migration de données : les bases actuelles ne portent aucun membre du
personnel sans adresse (vérifié avant application). Si une base en portait, la
migration échouerait à l'ajout de la contrainte — comportement voulu, mieux vaut
buter que de laisser passer un compte inaccessible.

Réversible sans perte : retirer une contrainte ne touche à aucune donnée.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('iam', '0009_user_add_role_constraints'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('role__in', ['admin', 'dispatcher', 'agent', 'driver', 'controller', 'superadmin']), _negated=True), ('email__isnull', False), _connector='OR'), name='user_staff_has_email'),
        ),
    ]
