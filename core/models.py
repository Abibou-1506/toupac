"""
TOUPAC Core — Modèles de base et champs personnalisés.
Tout modèle métier hérite de TenantModel.
"""
import uuid

from django.db import models
from django.utils import timezone


class UUIDv7Field(models.UUIDField):
    """Clé primaire UUID v7 (timestamp-ordered)."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("primary_key", True)
        kwargs.setdefault("default", uuid.uuid4)
        kwargs.setdefault("editable", False)
        super().__init__(*args, **kwargs)


class TimestampMixin(models.Model):
    """created_at / updated_at automatiques."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteMixin(models.Model):
    """Soft delete via deleted_at."""
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class TenantModel(TimestampMixin):
    """
    Modèle de base pour toutes les entités multi-tenant.

    **Manager par défaut : filtrage explicite.** Chaque ViewSet et chaque
    resolver appelle `.filter(tenant=request.tenant)` — ou son équivalent lié
    au contexte — de sa propre initiative. `TenantManager.get_queryset()` ne
    filtre **pas** de lui-même : l'isolation cross-tenant repose entièrement
    sur les filtres écrits à la main, et un `.filter()` oublié rendrait des
    lignes de toutes les compagnies.

    Le parti d'un filtrage explicite est documenté et vérifié — cf.
    `DECISIONS.md`, section « Multi-tenant et cross-tenant ». Il vaut aussi bien
    pour les vues que pour les resolvers de notification, qui reçoivent le
    tenant en paramètre pour la même raison.

    L'ancien docstring promettait un filtrage automatique « via
    TenantQuerySetMixin et TenantMiddleware » : c'était une promesse fausse, ni
    l'un ni l'autre n'existent dans le code. Corrigé au Ticket F.
    """
    id = UUIDv7Field()
    tenant = models.ForeignKey(
        "iam.Tenant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    """QuerySet filtré par tenant depuis le middleware."""
    def for_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantManager(models.Manager):
    """Manager utilisant TenantQuerySet."""
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_tenant(self, tenant):
        return self.get_queryset().for_tenant(tenant)
