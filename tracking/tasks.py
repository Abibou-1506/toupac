"""TOUPAC Tracking — Tâches Celery périodiques."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("toupac.tracking")


@shared_task
def purge_old_positions():
    """Supprime les positions GPS de plus de 90 jours (conformité RGPD)."""
    from tracking.models import Position
    cutoff = timezone.now() - timedelta(days=90)
    count, _ = Position.objects.filter(recorded_at__lt=cutoff).delete()
    logger.info(f"Purge positions : {count} positions supprimées (avant {cutoff.date()})")
    return count
