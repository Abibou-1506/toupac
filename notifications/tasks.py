"""TOUPAC Notifications — Tâches Celery d'envoi asynchrone."""
from celery import shared_task

from .services import NotificationService


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_async(self, tenant_id, event_type, channel, recipient, context_data, user_id=None, language="fr"):
    """
    Tâche Celery pour envoi asynchrone de notifications.
    Retry 3 fois avec 60s d'intervalle en cas d'échec.
    """
    from iam.models import Tenant, User

    tenant = Tenant.objects.get(id=tenant_id)
    user = User.objects.get(id=user_id) if user_id else None

    try:
        NotificationService.send_notification(
            tenant=tenant,
            event_type=event_type,
            channel=channel,
            recipient=recipient,
            context_data=context_data,
            user=user,
            language=language,
        )
    except Exception as exc:
        self.retry(exc=exc)


@shared_task
def send_bulk_notifications(tenant_id, event_type, channel, recipients_data, language="fr"):
    """
    Envoie une notification à plusieurs destinataires.
    recipients_data = [{"recipient": "+221...", "context_data": {...}, "user_id": "..."}, ...]
    """
    for r in recipients_data:
        send_notification_async.delay(
            tenant_id=tenant_id,
            event_type=event_type,
            channel=channel,
            recipient=r["recipient"],
            context_data=r["context_data"],
            user_id=r.get("user_id"),
            language=language,
        )
