"""Inscrit en base la doctrine « quel rôle vit dans quelle compagnie ».

Séparée de 0008 pour que l'assainissement des données soit acquis avant que la
base ne se mette à refuser. Réversible sans perte : retirer une contrainte ne
touche à aucune donnée.

Les trois contraintes doublent `User.clean()`. Ce n'est pas redondant :
`clean()` produit des messages lisibles dans les formulaires mais n'est jamais
appelé par `bulk_create`, `update()` ni par du SQL direct — c'est la base qui
tient la règle quand le code l'oublie.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0008_user_email_nullable_prep"),
    ]

    operations = [
        # Un chauffeur et un client peuvent partager un numéro (même humain,
        # deux rôles) : l'unicité ne vaut qu'entre CLIENT, où le téléphone
        # servira d'identifiant de connexion.
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                condition=models.Q(("role", "client"), models.Q(("phone", ""), _negated=True)),
                fields=("phone",),
                name="user_client_phone_unique",
            ),
        ),
        # CLIENT et SUPERADMIN sans compagnie ; rôles opérationnels avec ;
        # SERVICE_ACCOUNT libre (platform-bot global vs bot de compagnie).
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("role", "superadmin"), ("tenant__isnull", True)),
                    models.Q(("role", "client"), ("tenant__isnull", True)),
                    ("role", "service_account"),
                    models.Q(
                        ("role__in", ["admin", "dispatcher", "agent", "driver", "controller"]),
                        ("tenant__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="user_tenant_matches_role",
            ),
        ),
        # Un client sans e-mail ni téléphone serait introuvable à vie.
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("role", "client"), _negated=True),
                    ("email__isnull", False),
                    models.Q(("phone", ""), _negated=True),
                    _connector="OR",
                ),
                name="user_client_has_contact",
            ),
        ),
    ]
