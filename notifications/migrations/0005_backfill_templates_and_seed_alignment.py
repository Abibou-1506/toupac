"""Aligne les données existantes sur le catalogue, puis retire `subject`.

Trois opérations, dans cet ordre — le retrait de `subject` est en dernier pour
que le backfill ait encore la colonne sous la main (l'anti-critère du ticket
autorise explicitement backfill et suppression dans la même migration) :

1. `subject` → `title_template` sur les gabarits qui en portaient un.
2. Anciens `event_code` de seed → codes canoniques du catalogue.
3. RemoveField `subject`.

Collision non prévue par le ticket
----------------------------------
Deux commandes de seed coexistent et créaient des gabarits système (tenant=NULL)
avec des vocabulaires différents pour le même événement :

    seed_notification_templates.py   seed_demo.py            → code canonique
    trip_departure_reminder/sms      trip_reminder/sms       → notif.trip.reminder.v1
    delivery_complete/sms            parcel_delivered/sms    → notif.parcel.delivered.v1

Les deux membres de chaque paire visent la même clé unique
(tenant, event_code, channel, language) : un simple UPDATE violerait
`unique_template_per_tenant_event_channel_lang`. On garde donc le gabarit issu
de `seed_demo` (celui que le ticket désigne comme canonique et qui porte le jeu
de démo) et on supprime le doublon. C'est sans perte réelle : les deux
commandes sont idempotentes et régénèrent leurs gabarits à la demande.
"""
from django.db import migrations

#: Ancien vocabulaire → code canonique. Couvre les deux commandes de seed.
LEGACY_TO_CANONICAL = {
    "reservation_confirmed": "notif.order.confirmed.v1",
    "trip_reminder": "notif.trip.reminder.v1",
    "trip_departure_reminder": "notif.trip.reminder.v1",
    "parcel_delivered": "notif.parcel.delivered.v1",
    "delivery_complete": "notif.parcel.delivered.v1",
    "payment_received": "notif.payment.confirmed.v1",
}

#: En cas de collision sur la clé unique, l'ancien code à conserver. Les autres
#: prétendants au même code canonique sont supprimés.
COLLISION_WINNERS = {
    "notif.trip.reminder.v1": "trip_reminder",
    "notif.parcel.delivered.v1": "parcel_delivered",
}


def forward(apps, schema_editor):
    Template = apps.get_model("notifications", "NotificationTemplate")
    Log = apps.get_model("notifications", "NotificationLog")

    # 1. subject → title_template, sans écraser un title_template déjà rempli.
    for template in Template.objects.exclude(subject="").filter(title_template=""):
        template.title_template = template.subject
        template.save(update_fields=["title_template"])

    # 2. Gabarits : résoudre les collisions avant de renommer.
    for canonical, winner in COLLISION_WINNERS.items():
        losers = [code for code, target in LEGACY_TO_CANONICAL.items()
                  if target == canonical and code != winner]
        # On ne supprime un perdant que si le gagnant occupe réellement la même
        # clé — sinon le perdant est le seul porteur de l'événement et doit
        # simplement être renommé par l'étape suivante.
        for loser in losers:
            for row in Template.objects.filter(event_code=loser):
                clash = Template.objects.filter(
                    tenant=row.tenant, event_code=winner,
                    channel=row.channel, language=row.language,
                ).exists()
                if clash:
                    row.delete()

    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        Template.objects.filter(event_code=legacy).update(event_code=canonical)

    # 3. Journaux : même vocabulaire, sinon la colonne mélange deux langages et
    # tout filtre/statistique par event_code devient faux. Aucune contrainte
    # d'unicité ici, donc pas de collision possible.
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        Log.objects.filter(event_code=legacy).update(event_code=canonical)


def reverse(apps, schema_editor):
    """Noop assumé.

    Le mapping est surjectif (`trip_reminder` et `trip_departure_reminder`
    tombent tous deux sur `notif.trip.reminder.v1`) : l'inverse est ambigu et
    les doublons supprimés ne sont pas reconstituables depuis la base. Un retour
    arrière se rattrape en rejouant les commandes de seed, qui écrivent
    désormais directement les codes canoniques. Laisser les données sur le
    vocabulaire du catalogue est de toute façon inoffensif pour le schéma
    antérieur, qui ne contraint pas la forme du code.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_enrich_template_and_create_notification"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
        migrations.RemoveField(
            model_name="notificationtemplate",
            name="subject",
        ),
    ]
