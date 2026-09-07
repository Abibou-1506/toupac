"""Retire le concept d'abonnement d'une compagnie à un service plateforme.

Sur-engineering constaté à l'usage. `TenantSubscription` modélisait une
souscription commerciale — une compagnie « s'abonne » au chatbot Toupac BI —
alors que la réalité produit est l'inverse : un service plateforme est une
fonctionnalité de TOUPAC, disponible pour toute compagnie dès sa création. La
table n'a jamais servi qu'à ajouter une étape d'onboarding manuelle entre la
création d'une compagnie et le moment où le partenaire pouvait la servir.

Le cloisonnement n'en souffre pas : il repose sur les scopes de la clé, sur la
révocation immédiate et sur le journal d'audit — pas sur cette liste.

Réversible au sens du schéma (la table est recréée en arrière), mais son contenu
est perdu. C'est assumé : les lignes ne portaient qu'une autorisation que plus
rien ne consulte.
"""
from django.db import migrations


def report_removed_rows(apps, schema_editor):
    """Trace ce qui disparaît, pour que la suppression laisse une trace lisible."""
    TenantSubscription = apps.get_model("iam", "TenantSubscription")
    count = TenantSubscription.objects.count()
    if count:
        print(
            f"  [USR-4] Suppression de {count} abonnement(s) plateforme. Le concept "
            "est retiré : tout service plateforme accède désormais à toute "
            "compagnie active."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0010_user_staff_email_constraint"),
    ]

    operations = [
        migrations.RunPython(report_removed_rows, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="tenantsubscription",
            name="unique_tenant_service_subscription",
        ),
        migrations.DeleteModel(name="TenantSubscription"),
    ]
