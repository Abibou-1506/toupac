"""TOUPAC Fleet — Tâches Celery périodiques."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("toupac.fleet")


@shared_task
def check_expiring_documents():
    """Vérifie les documents véhicules qui expirent dans les 30 prochains jours."""
    from fleet.models import VehicleDocument
    cutoff = timezone.now().date() + timedelta(days=30)
    expiring = VehicleDocument.objects.filter(
        expiry_date__lte=cutoff,
        expiry_date__gte=timezone.now().date(),
        status="valid",
    ).select_related("vehicle", "vehicle__tenant")

    count = expiring.count()
    for doc in expiring:
        logger.warning(
            f"Document {doc.get_type_display()} du véhicule {doc.vehicle.plate_number} "
            f"(tenant: {doc.vehicle.tenant.name}) expire le {doc.expiry_date}"
        )

    logger.info(f"Vérification documents : {count} document(s) expirant dans 30 jours")
    return count
