"""Seed des templates de notification système (tenant=NULL)."""
from django.core.management.base import BaseCommand

from notifications.models import NotificationTemplate

#: Corps du code de connexion, partagé par SMS et WhatsApp — même contrainte de
#: longueur, même absence de mise en forme. Les variables sont celles déclarées
#: par `notif.auth.otp_signin.v1` dans notifications/catalog.py : les renommer
#: ici sans les renommer là-bas produirait un message avec des trous.
_OTP_SHORT_BODY = (
    "Votre code de connexion TOUPAC est {{otp}}. "
    "Il expire dans {{expires_in_minutes}} minutes. Ne le communiquez à personne."
)

SYSTEM_TEMPLATES = [
    # ─── Connexion par code (AUTH-01) ───
    {
        "event_code": "notif.auth.otp_signin.v1",
        "channel": NotificationTemplate.Channel.SMS,
        "language": "fr",
        "title_template": "TOUPAC",
        "template_body": _OTP_SHORT_BODY,
    },
    {
        "event_code": "notif.auth.otp_signin.v1",
        "channel": NotificationTemplate.Channel.WHATSAPP,
        "language": "fr",
        "title_template": "TOUPAC",
        "template_body": _OTP_SHORT_BODY,
    },
    {
        "event_code": "notif.auth.otp_signin.v1",
        "channel": NotificationTemplate.Channel.EMAIL,
        "language": "fr",
        "title_template": "Votre code de connexion TOUPAC",
        "template_body": (
            "Bonjour,\n\n"
            "Votre code de connexion est {{otp}}. "
            "Il expire dans {{expires_in_minutes}} minutes.\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
            "personne ne peut se connecter sans ce code.\n\n"
            "L'équipe TOUPAC"
        ),
    },
    {
        "event_code": "notif.auth.otp_signin.v1",
        "channel": NotificationTemplate.Channel.IN_APP,
        "language": "fr",
        "title_template": "Code de connexion",
        "template_body": "{{otp}} — valable {{expires_in_minutes}} minutes.",
    },
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
                defaults={
                    "template_body": spec["template_body"],
                    "title_template": spec.get("title_template", ""),
                },
            )
            label = "créé" if created else "déjà présent"
            self.stdout.write(f"  {template.event_code} / {template.channel} / {template.language} — {label}")
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {created_count} template(s) créé(s), {len(SYSTEM_TEMPLATES) - created_count} déjà présent(s)."
        ))
