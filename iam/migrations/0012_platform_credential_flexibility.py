"""Assouplit l'expiration et l'allowlist d'une clé plateforme.

Deux garde-fous posés au ticket initial se sont révélés plus coûteux que
protecteurs :

- **Expiration obligatoire à 90 jours.** Chaque rotation impose de retransmettre
  le secret à l'équipe partenaire — autant d'occasions de le voir fuiter, et une
  coupure de service si la bascule tarde. Le champ devient facultatif : qui veut
  programmer une échéance le peut toujours, mais le défaut est une clé qui vit
  jusqu'à sa révocation.
- **Allowlist IP obligatoire hors développement.** Un service partenaire sans
  serveur (fonctions managées, multi-région) n'a pas d'adresse de sortie stable
  à déclarer. La liste vide devient légitime partout et signifie « pas de
  filtrage d'origine », le portail partenaires recommandant de la renseigner
  quand c'est possible.

Ce qui protège réellement reste inchangé : scopes explicites sans super-scope,
révocation immédiate, journal d'audit par appel.

Aucune donnée touchée — seuls la nullabilité et les libellés changent. Le retour
arrière échouerait sur les clés sans échéance, ce qui est le bon signal.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("iam", "0011_drop_tenant_subscription"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platformcredential",
            name="allowed_ips",
            field=models.JSONField(
                blank=True, default=list,
                help_text='Liste de CIDR autorisés, ex : ["52.34.10.5/32", "10.0.0.0/24"]. '
                          "Vide = aucun filtrage d'origine. Fortement recommandé quand le "
                          "service partenaire dispose d'une IP de sortie stable.",
                verbose_name="IP autorisées (CIDR)",
            ),
        ),
        migrations.AlterField(
            model_name="platformcredential",
            name="expires_at",
            field=models.DateTimeField(
                blank=True, null=True,
                help_text="Facultatif. Sans date, la clé reste valable jusqu'à sa révocation "
                          "(is_active). Une expiration impose de repartager le secret au "
                          "partenaire — à ne programmer que si le contrat l'exige.",
                verbose_name="Expire le",
            ),
        ),
    ]
