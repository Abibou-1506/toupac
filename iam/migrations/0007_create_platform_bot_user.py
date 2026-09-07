"""Crée le compte technique global portant les requêtes des clés plateforme.

Un seul compte pour toute la plateforme, `tenant=None` — à la différence des
comptes de service tenant (`api-bot@<slug>.internal`), provisionnés un par
compagnie par le signal post_save sur Tenant.

`make_password(None)` plutôt que `set_unusable_password()` : le modèle
historique rendu par `apps.get_model` n'expose que les champs, pas les méthodes
personnalisées de la classe réelle — appeler la méthode ici lèverait un
AttributeError. Les deux produisent la même valeur de mot de passe inutilisable.
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations

PLATFORM_BOT_EMAIL = "platform-bot@toupac.internal"


def create_platform_bot(apps, schema_editor):
    User = apps.get_model("iam", "User")
    User.objects.update_or_create(
        email=PLATFORM_BOT_EMAIL,
        defaults={
            "first_name": "Platform",
            "last_name": "Bot",
            "tenant": None,
            "role": "service_account",
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
            "password": make_password(None),
        },
    )


def delete_platform_bot(apps, schema_editor):
    """
    Réversible pour de vrai : le compte n'a aucune donnée propre à perdre.

    Les `PlatformCredential` ne le référencent pas (elles n'ont pas de FK vers
    lui — il est résolu à l'authentification), sa suppression ne casse donc
    aucune ligne. Et s'il manque, `User.get_or_create_platform_bot()` le
    recrée à la première requête plateforme.
    """
    apps.get_model("iam", "User").objects.filter(email=PLATFORM_BOT_EMAIL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0006_add_platform_models"),
    ]

    operations = [
        migrations.RunPython(create_platform_bot, delete_platform_bot),
    ]
