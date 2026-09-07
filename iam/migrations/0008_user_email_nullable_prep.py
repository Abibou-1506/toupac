"""Rend l'e-mail facultatif et met les données existantes en conformité.

Étape préparatoire, volontairement sans contrainte : les contraintes arrivent en
0009, une fois les données saines. Les séparer permet de rejouer l'assainissement
seul en cas d'échec, et de lire dans le journal des migrations laquelle des deux
a buté.

L'ordre au sein du fichier compte : `AlterField` d'abord, parce que
l'assainissement écrit des NULL dans une colonne qui n'en acceptait pas.
"""
from django.db import migrations, models

STAFF_ROLES = ["admin", "dispatcher", "agent", "driver", "controller"]

#: Valeur que django-guardian donne à USERNAME_FIELD pour son utilisateur
#: anonyme. Recopiée plutôt qu'importée : une migration doit rester lisible et
#: stable même si le réglage change plus tard.
GUARDIAN_ANONYMOUS_EMAIL = "AnonymousUser"


def sanitize(apps, schema_editor):
    User = apps.get_model("iam", "User")

    # 1. Un e-mail vide devient NULL. La colonne est UNIQUE : deux chaînes vides
    # se heurteraient, deux NULL non (PostgreSQL les tient pour distincts).
    User.objects.filter(email="").update(email=None)

    # 2. Les CLIENT perdent leur rattachement : un passager est client de
    # TOUPAC, pas d'une compagnie. Aucune ligne concernée dans les bases
    # actuelles — le seed n'a jamais créé de CLIENT — mais une base de
    # production ou un jeu de test local peut en porter.
    User.objects.filter(role="client", tenant__isnull=False).update(tenant=None)

    # 3. L'utilisateur anonyme de django-guardian arrive en rôle `agent` sans
    # tenant, combinaison que 0009 interdit. Il est requalifié en compte de
    # service, seul rôle laissé libre de tenant — cf. iam/guardian.py, qui pose
    # la même valeur pour les créations futures.
    User.objects.filter(email=GUARDIAN_ANONYMOUS_EMAIL).update(
        role="service_account", tenant=None,
    )

    # 4. Un superadmin rattaché à une compagnie est une incohérence historique.
    User.objects.filter(role="superadmin", tenant__isnull=False).update(tenant=None)


def desanitize(apps, schema_editor):
    """Rétablit ce qui empêcherait un retour en arrière du schéma.

    Seul le NULL d'e-mail bloque vraiment : la colonne redevient NOT NULL en
    sens inverse. Les rattachements de tenant effacés ne sont pas restaurables
    (l'information est perdue) et n'ont pas à l'être — le schéma antérieur les
    acceptait sans les exiger.
    """
    User = apps.get_model("iam", "User")
    User.objects.filter(email=None).update(email="")


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("iam", "0007_create_platform_bot_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(
                blank=True, max_length=254, null=True, unique=True, verbose_name="Email",
            ),
        ),
        migrations.RunPython(sanitize, desanitize),
    ]
