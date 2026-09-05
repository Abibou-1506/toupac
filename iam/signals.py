"""
TOUPAC IAM — Signaux.

Le compte de service doit exister dès la création du tenant, pas au premier
appel à `issue()` : c'est un invariant du tenant, pas un effet de bord de
l'émission d'une clé. Un provisionnement paresseux laisserait une fenêtre où
un tenant existe sans porteur possible pour ses clés.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from iam.models import Tenant


@receiver(post_save, sender=Tenant, dispatch_uid="iam.provision_service_account")
def provision_service_account(sender, instance, created, **kwargs):
    if created:
        instance.get_or_create_service_account()
