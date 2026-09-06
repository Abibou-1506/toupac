"""TOUPAC Notifications — Service central d'envoi (templates + provider + log)."""
from django.db.models import Q
from django.template import Context, Template
from django.utils import timezone

from .models import NotificationLog, NotificationTemplate


class NotificationService:
    """Service central d'envoi de notifications."""

    @staticmethod
    def send_notification(tenant, event_code, channel, recipient, context_data, user=None, language="fr"):
        """
        1. Cherche le template (tenant-specific, puis système).
        2. Rend le template avec context_data.
        3. Envoie via le provider approprié.
        4. Crée un NotificationLog.

        context_data ex: {"passenger_name": "Moussa", "route_name": "Dakar → Bamako",
                          "departure_date": "25/08/2026", "seat_label": "A12"}
        """
        template_obj = (
            NotificationTemplate.objects.filter(
                event_code=event_code, channel=channel, language=language, is_active=True,
            )
            .filter(Q(tenant=tenant) | Q(tenant__isnull=True))
            .order_by("-tenant_id")  # tenant-specific en priorité sur système
            .first()
        )

        if not template_obj:
            # N-08 traçabilité : la notification cherche un template absent.
            # On log (status=failed, failure_reason préfixé "no_template:") au
            # lieu de retourner None en silence — aucune notif ne disparaît, et
            # l'exploitation détecte les templates manquants sans fouiller les
            # logs Django : NotificationLog.objects.filter(
            #   status="failed", failure_reason__startswith="no_template:").
            return NotificationLog.objects.create(
                tenant=tenant,
                user=user,
                channel=channel,
                recipient=recipient,
                event_code=event_code,
                content="",
                status=NotificationLog.Status.FAILED,
                provider="",
                provider_message_id="",
                failure_reason=f"no_template:{event_code}/{channel}/{language}",
            )

        django_template = Template(template_obj.template_body)
        rendered = django_template.render(Context(context_data))
        subject_rendered = ""
        if template_obj.title_template:
            subject_rendered = Template(template_obj.title_template).render(Context(context_data))

        provider = NotificationService._get_provider(channel)
        result = provider.send(recipient=recipient, message=rendered, subject=subject_rendered)

        log = NotificationLog.objects.create(
            tenant=tenant,
            user=user,
            channel=channel,
            recipient=recipient,
            event_code=event_code,
            content=rendered[:500],  # tronqué
            status="sent" if result.success else "failed",
            provider=provider.__class__.__name__.lower().replace("provider", ""),
            provider_message_id=result.provider_message_id,
            failure_reason=result.error_message if not result.success else "",
            sent_at=timezone.now() if result.success else None,
        )
        return log

    @staticmethod
    def _get_provider(channel):
        """Retourne le provider approprié selon le canal."""
        # V1 : tout passe par ConsoleProvider
        # V2 : switch sur channel → africastalking (sms), firebase (push), smtp (email)
        from notifications.providers.console import ConsoleProvider
        return ConsoleProvider()
