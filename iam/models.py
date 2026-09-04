"""
TOUPAC IAM — Tenants, Users, API credentials, Audit logs.
"""
import secrets

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError

from core.models import SoftDeleteMixin, TimestampMixin, UUIDv7Field

# ─── Tenant ───

class Tenant(TimestampMixin, models.Model):
    """
    Racine multi-tenant. Une ligne = une compagnie de transport cliente.
    """
    class Status(models.TextChoices):
        ACTIVE = "active", "Actif"
        SUSPENDED = "suspended", "Suspendu"
        TRIAL = "trial", "Essai"

    class Plan(models.TextChoices):
        FREE = "free", "Gratuit"
        STARTER = "starter", "Starter"
        PRO = "pro", "Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    id = UUIDv7Field()
    name = models.CharField("Nom", max_length=200)
    slug = models.SlugField("Slug", max_length=100, unique=True)
    country_code = models.CharField("Pays (ISO)", max_length=2, default="SN")
    currency = models.CharField("Devise", max_length=3, default="XOF")
    timezone = models.CharField("Fuseau horaire", max_length=50, default="Africa/Dakar")
    language = models.CharField("Langue", max_length=2, default="fr")
    settings = models.JSONField("Paramètres", default=dict, blank=True)
    status = models.CharField("Statut", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    subscription_plan = models.CharField(
        "Plan", max_length=30, choices=Plan.choices, default=Plan.FREE, blank=True
    )

    class Meta:
        db_table = "iam_tenants"
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ─── User ───

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.SUPERADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimestampMixin, SoftDeleteMixin):
    """
    Utilisateur TOUPAC. Le rôle est en ENUM pour simplifier le RBAC V1.
    Le tenant est optionnel pour les super-admins TOUPAC.
    """
    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Super Admin TOUPAC"
        ADMIN = "admin", "Admin compagnie"
        DISPATCHER = "dispatcher", "Dispatcher"
        AGENT = "agent", "Agent de guichet"
        DRIVER = "driver", "Chauffeur"
        CONTROLLER = "controller", "Contrôleur"
        CLIENT = "client", "Client"

    id = UUIDv7Field()
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Compagnie",
    )
    email = models.EmailField("Email", unique=True)
    phone = models.CharField("Téléphone", max_length=20, blank=True)
    first_name = models.CharField("Prénom", max_length=100)
    last_name = models.CharField("Nom", max_length=100)
    role = models.CharField("Rôle", max_length=20, choices=Role.choices, default=Role.AGENT)
    is_active = models.BooleanField("Actif", default=True)
    is_staff = models.BooleanField("Staff (accès admin)", default=False)
    last_login_at = models.DateTimeField("Dernière connexion", null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "iam_users"
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["tenant", "role"]),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


# ─── API Credentials ───

class ApiCredential(TimestampMixin, models.Model):
    id = UUIDv7Field()
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_credentials")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="api_credentials")
    name = models.CharField("Nom", max_length=100)
    key_prefix = models.CharField("Préfixe clé", max_length=12)
    key_hash = models.CharField("Hash clé", max_length=255)
    scopes = models.JSONField("Scopes", default=list, blank=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "iam_api_credentials"
        verbose_name = "Clé API"
        verbose_name_plural = "Clés API"

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    def clean(self):
        from iam.scopes import validate_scopes

        unknown = validate_scopes(self.scopes)
        if unknown:
            raise ValidationError({"scopes": f"Scope(s) inconnu(s) : {', '.join(unknown)}"})

    def has_scope(self, scope_name):
        """True si le scope est accordé, directement ou via le super-scope admin."""
        from iam.scopes import ADMIN_SCOPE

        granted = self.scopes or []
        return ADMIN_SCOPE in granted or scope_name in granted

    @classmethod
    def issue(cls, tenant, name, scopes, user=None, expires_at=None):
        """
        Crée une clé API et retourne (credential, clé_en_clair).

        La clé en clair n'est jamais stockée ni réaffichable : seul son hash
        l'est. C'est le seul moment où l'appelant peut la transmettre.
        """
        from django.contrib.auth.hashers import make_password

        prefix = f"tpc_{secrets.token_hex(4)}"  # 12 caractères, tient dans key_prefix
        secret = secrets.token_urlsafe(32)
        credential = cls(
            tenant=tenant, user=user, name=name, scopes=list(scopes),
            key_prefix=prefix, key_hash=make_password(secret), expires_at=expires_at,
        )
        credential.full_clean(exclude=["user"])
        credential.save()
        return credential, f"{prefix}.{secret}"


# ─── Audit Log ───

class AuditLog(models.Model):
    id = UUIDv7Field()
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, related_name="audit_logs")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_logs")
    action = models.CharField(max_length=50, db_index=True)
    resource_type = models.CharField(max_length=50)
    resource_id = models.UUIDField(null=True, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "iam_audit_logs"
        verbose_name = "Log d'audit"
        verbose_name_plural = "Logs d'audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "resource_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} {self.resource_type} by {self.user}"


# ─── User Devices (push tokens) ───

class UserDevice(TimestampMixin, models.Model):
    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    id = UUIDv7Field()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    platform = models.CharField(max_length=10, choices=Platform.choices)
    push_token = models.CharField(max_length=500)
    device_model = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "iam_user_devices"
        verbose_name = "Appareil"
        verbose_name_plural = "Appareils"

    def __str__(self):
        return f"{self.user} — {self.platform} ({self.device_model})"
