"""
TOUPAC Notifications — Livraison asynchrone d'un envoi déjà tracé.

Le service a fait le travail décisif — résoudre, rendre, écrire en base — avant
de mettre en file. Il ne reste ici qu'à remettre le message au fournisseur et à
consigner le résultat. Cette répartition a une conséquence utile : un courtier
indisponible ne perd aucune notification, elle attend en base au statut
`queued`, et une reprise la retrouvera.

La tâche est **idempotente** : rejouée sur un envoi déjà traité, elle ne fait
rien. Celery peut livrer un message deux fois, et un opérateur peut relancer une
tâche à la main ; ni l'un ni l'autre ne doit produire un second SMS.
"""
import logging

from celery import shared_task
from django.utils import timezone

from .models import NotificationLog
from .retries import get_retry_policy

logger = logging.getLogger("toupac.notifications")

#: Plafond déclaré à Celery. La limite réelle est celle de la politique du
#: canal, lue à l'exécution — Celery exige une borne à la déclaration, avant
#: que le canal ne soit connu.
_MAX_RETRIES_CEILING = 3


@shared_task(bind=True, max_retries=_MAX_RETRIES_CEILING)
def send_notification_log(self, log_id):
    """Remet au fournisseur l'envoi `log_id`, puis consigne le résultat."""
    from .services import NotificationService

    log = NotificationLog.objects.select_related("notification").filter(pk=log_id).first()
    if log is None:
        # Purge ou suppression entre la mise en file et l'exécution.
        return
    if log.status != NotificationLog.Status.QUEUED:
        # Déjà traité : livraison en double par le courtier, ou relance
        # manuelle. Refaire l'envoi coûterait un second message.
        return

    policy = get_retry_policy(log.channel)

    try:
        provider = NotificationService._get_provider(log.channel)
        result = provider.send(
            recipient=log.recipient,
            message=log.content,
            subject=log.notification.title if log.notification_id else "",
        )
    except Exception as exc:  # panne du fournisseur
        if self.request.retries < policy.max_retries:
            raise self.retry(
                exc=exc, countdown=policy.countdown_for(self.request.retries),
            ) from exc
        _mark_failed(log, f"provider_error:{log.channel}:{exc}")
        return

    if result.success:
        log.status = NotificationLog.Status.SENT
        log.provider = provider.__class__.__name__.lower().replace("provider", "")
        log.provider_message_id = result.provider_message_id or ""
        log.sent_at = timezone.now()
        log.failure_reason = ""
        log.save(update_fields=[
            "status", "provider", "provider_message_id", "sent_at", "failure_reason",
        ])
        return

    # Le fournisseur a répondu sans lever : un refus, pas une panne. Le
    # réessayer suit la même politique — un destinataire injoignable le reste,
    # mais une passerelle qui rend une erreur temporaire mérite une seconde
    # chance sur les canaux gratuits.
    if self.request.retries < policy.max_retries:
        raise self.retry(countdown=policy.countdown_for(self.request.retries))

    log.provider = provider.__class__.__name__.lower().replace("provider", "")
    _mark_failed(log, f"provider_error:{log.channel}:{result.error_message or 'refus du fournisseur'}")


def _mark_failed(log, failure_reason):
    log.status = NotificationLog.Status.FAILED
    log.failure_reason = failure_reason[:300]
    log.sent_at = None
    log.save(update_fields=["status", "failure_reason", "sent_at", "provider"])
    logger.warning("Envoi %s en échec définitif : %s", log.pk, failure_reason)


@shared_task(bind=True, max_retries=_MAX_RETRIES_CEILING, default_retry_delay=60)
def send_notification_async(self, tenant_id, event_code, channel, recipient, context_data,
                            user_id=None, language="fr"):
    """
    Déprécié — conservé pour l'endpoint d'envoi manuel, pas encore migré.

    Délègue à l'adaptateur de compatibilité, qui émet lui-même un
    `DeprecationWarning`. Retrait prévu au Ticket F, avec celui de
    `send_notification()`.
    """
    from iam.models import Tenant, User

    from .services import NotificationService

    tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
    user = User.objects.filter(pk=user_id).first() if user_id else None

    NotificationService.send_notification(
        tenant=tenant, event_code=event_code, channel=channel, recipient=recipient,
        context_data=context_data, user=user, language=language,
    )
