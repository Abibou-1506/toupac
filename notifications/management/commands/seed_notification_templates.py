"""Seed des templates de notification système (tenant=NULL)."""
from django.core.management.base import BaseCommand

from notifications.models import NotificationTemplate

SYSTEM_TEMPLATES = [
    {
        "event_code": "notif.order.confirmed.v1",
        "channel": NotificationTemplate.Channel.SMS,
        "language": "fr",
        "template_body": (
            "Bonjour {{passenger_name}}, votre billet {{route_name}} du {{departure_date}} "
            "est confirmé. Siège : {{seat_label}}. Bon voyage !"
        ),
    },
    {
        "event_code": "notif.trip.reminder.v1",
        "channel": NotificationTemplate.Channel.SMS,
        "language": "fr",
        "template_body": (
            "Rappel : votre voyage {{route_name}} part à {{departure_time}}. "
            "Présentez-vous à la gare 30 min avant le départ."
        ),
    },
    {
        "event_code": "notif.parcel.delivered.v1",
        "channel": NotificationTemplate.Channel.SMS,
        "language": "fr",
        "template_body": (
            "Votre colis {{tracking_number}} a été livré à {{recipient_name}}. "
            "Merci d'avoir utilisé TOUPAC !"
        ),
    },
    {
        "event_code": "notif.payment.confirmed.v1",
        "channel": NotificationTemplate.Channel.SMS,
        "language": "fr",
        "template_body": (
            "Paiement de {{amount}} XOF reçu pour {{description}}. Réf: {{payment_ref}}. "
            "Merci !"
        ),
    },
]


class Command(BaseCommand):
    help = "Crée les templates de notification système (tenant=NULL), idempotent."

    def handle(self, *args, **options):
        created_count = 0
        for spec in SYSTEM_TEMPLATES:
            template, created = NotificationTemplate.objects.get_or_create(
                tenant=None,
                event_code=spec["event_code"],
                channel=spec["channel"],
                language=spec["language"],
                defaults={"template_body": spec["template_body"]},
            )
            label = "créé" if created else "déjà présent"
            self.stdout.write(f"  {template.event_code} / {template.channel} / {template.language} — {label}")
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {created_count} template(s) créé(s), {len(SYSTEM_TEMPLATES) - created_count} déjà présent(s)."
        ))
