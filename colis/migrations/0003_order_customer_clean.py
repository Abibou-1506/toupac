"""Vide `Order.customer` quand il ne désigne pas un compte client.

`Order.customer` existait avant le chantier client global, sans que sa
sémantique soit tranchée : il a pu recevoir n'importe quel utilisateur, y
compris un agent de guichet saisissant la commande. Depuis USR-3, ce champ
désigne le **commanditaire** du colis, donc un compte de rôle client.

Un lien qui pointe ailleurs n'est pas seulement incohérent : il ferait
apparaître la commande dans le `/customer/my-orders/` de la mauvaise personne.
On le retire — les coordonnées du client restent dans `customer_name` et
`customer_phone`, qui existent précisément comme repli.

Aucune ligne concernée dans les bases actuelles (audit avant écriture : zéro
commande porte un `customer`). La migration existe pour les environnements qui
ont accumulé des saisies manuelles.

Réversible en `noop` assumé : le lien effacé n'est pas reconstituable — c'est
justement parce qu'il était faux qu'il part. Le repli texte, lui, est intact.
"""
from django.db import migrations


def clean_non_client_customers(apps, schema_editor):
    Order = apps.get_model("colis", "Order")

    misattributed = Order.objects.filter(customer__isnull=False).exclude(
        customer__role="client",
    )
    count = misattributed.count()
    if count:
        misattributed.update(customer=None)
        print(f"  [USR-3] {count} commande(s) : customer vidé (ne désignait pas un client).")


class Migration(migrations.Migration):

    dependencies = [
        ("colis", "0002_order_trip"),
        # La contrainte de rôle d'USR-1 doit être posée : sans elle, un client
        # pourrait encore porter une compagnie et le tri serait faussé.
        ("iam", "0010_user_staff_email_constraint"),
    ]

    operations = [
        migrations.RunPython(clean_non_client_customers, migrations.RunPython.noop),
    ]
