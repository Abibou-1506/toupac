"""
Provisionne le compte de service des tenants créés avant le signal.

Le signal `post_save` ne couvre que les créations à venir : les tenants déjà
en base (dev, staging, démo) n'auraient aucun porteur pour leurs clés API.
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations

SERVICE_ACCOUNT_ROLE = "service_account"


def backfill_service_accounts(apps, schema_editor):
    # apps.get_model plutôt que l'import direct : le modèle historique de la
    # migration, sans les méthodes Python du modèle courant.
    Tenant = apps.get_model("iam", "Tenant")
    User = apps.get_model("iam", "User")

    for tenant in Tenant.objects.all():
        email = f"api-bot@{tenant.slug}.internal"
        if User.objects.filter(email=email).exists():
            continue
        User.objects.create(
            email=email,
            first_name="API", last_name="Bot",
            tenant=tenant, role=SERVICE_ACCOUNT_ROLE,
            # set_unusable_password() n'est pas disponible sur le modèle
            # historique : make_password(None) produit la même valeur ("!" +
            # aléatoire), c'est-à-dire un hash qui ne peut correspondre à
            # aucun mot de passe.
            password=make_password(None),
            is_active=True, is_staff=False, is_superuser=False,
        )


def remove_service_accounts(apps, schema_editor):
    """
    Volontairement inerte.

    Supprimer les comptes de service casserait les clés API qui les portent
    (ApiCredential.user est SET_NULL : les clés deviendraient orphelines, donc
    inutilisables). Une descente de migration ne doit pas révoquer des accès
    en production ; les comptes restent, inoffensifs sans clé associée.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0003_alter_user_role"),
    ]

    operations = [
        migrations.RunPython(backfill_service_accounts, remove_service_accounts),
    ]
