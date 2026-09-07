"""
TOUPAC IAM — Tenants, Users, API credentials, Audit logs.
"""
import secrets
from datetime import timedelta
from ipaddress import ip_address, ip_network

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

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

    @property
    def service_account_email(self):
        # `.internal` est un TLD réservé (ICANN, 2024) : non routable, aucune
        # adresse n'y reçoit de courrier. Marqueur non ambigu de compte technique.
        return f"api-bot@{self.slug}.internal"

    def get_or_create_service_account(self):
        """
        Compte technique portant les clés API du tenant. Idempotent.

        Une clé ne doit pas dépendre d'un salarié : désactiver l'humain porteur
        rendait toutes ses clés orphelines, donc 401. Ce compte ne peut pas
        s'authentifier (mot de passe inutilisable) ni entrer dans le
        back-office ; il n'existe que pour satisfaire `IsAuthenticated` et les
        FK `created_by` en aval des écritures faites par API.
        """
        service_account = User.objects.filter(email=self.service_account_email).first()
        if service_account is not None:
            return service_account

        service_account = User(
            email=self.service_account_email,
            first_name="API", last_name="Bot",
            tenant=self, role=User.Role.SERVICE_ACCOUNT,
            is_active=True, is_staff=False, is_superuser=False,
        )
        service_account.set_unusable_password()
        service_account.save()
        return service_account


# ─── User ───

class UserManager(BaseUserManager):
    def create_user(self, email=None, password=None, **extra_fields):
        """
        Crée un utilisateur. Au moins un identifiant de contact est exigé.

        L'e-mail n'est plus obligatoire depuis que le rôle CLIENT existe sans
        compagnie : un passager recruté par le chatbot WhatsApp n'est connu que
        par son téléphone. `phone` continue de passer par `extra_fields` — lui
        donner un paramètre nommé changerait la signature pour tous les
        appelants existants sans rien apporter.
        """
        phone = extra_fields.get("phone") or ""
        if not email and not phone:
            raise ValueError("Un utilisateur doit avoir au moins un email ou un téléphone.")
        # None et non "" : la colonne est UNIQUE, et PostgreSQL ne considère pas
        # deux NULL comme égaux — alors que deux chaînes vides le seraient.
        email = self.normalize_email(email) if email else None
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
        SERVICE_ACCOUNT = "service_account", "Compte de service"

    id = UUIDv7Field()
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Compagnie",
    )
    # `null=True` avec `unique=True` : PostgreSQL traite deux NULL comme
    # distincts dans un index unique, ce qui donne exactement « unique quand
    # renseigné ». C'est aussi la seule forme qui satisfait la vérification
    # système d'`AbstractBaseUser` — une UniqueConstraint partielle laisse
    # Django émettre auth.W004, puisqu'elle ne garantit pas l'unicité globale.
    # D'où l'exception assumée à la règle « pas de null sur un champ texte » :
    # e-mail absent = NULL, jamais "".
    email = models.EmailField("Email", unique=True, blank=True, null=True)
    phone = models.CharField("Téléphone", max_length=20, blank=True)
    first_name = models.CharField("Prénom", max_length=100)
    last_name = models.CharField("Nom", max_length=100)
    role = models.CharField("Rôle", max_length=20, choices=Role.choices, default=Role.AGENT)
    is_active = models.BooleanField("Actif", default=True)
    is_staff = models.BooleanField("Staff (accès admin)", default=False)
    last_login_at = models.DateTimeField("Dernière connexion", null=True, blank=True)
    notification_preferences = models.JSONField(
        "Préférences de notification", default=dict, blank=True,
        help_text="Dict de catégories opt-in/opt-out. Ex: {'marketing': False, 'trip_updates': True}. "
                  "Clé absente = opt-in ; les catégories de notifications.preferences.NEVER_OPT_OUT "
                  "ignorent la valeur.",
    )

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
        constraints = [
            # Un chauffeur et un client peuvent partager un numéro — c'est le
            # même humain qui voyage aussi comme passager. L'unicité ne vaut
            # donc qu'entre CLIENT, où le téléphone sert d'identifiant de
            # connexion (OTP, ticket USR-2).
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(role="client") & ~models.Q(phone=""),
                name="user_client_phone_unique",
            ),
            # Doctrine produit inscrite en base : un client est client de
            # TOUPAC, pas d'une compagnie ; un rôle opérationnel n'existe que
            # dans une compagnie. Le compte de service est le seul cas
            # légitimement libre (platform-bot global vs bot de compagnie).
            models.CheckConstraint(
                condition=(
                    (models.Q(role="superadmin") & models.Q(tenant__isnull=True))
                    | (models.Q(role="client") & models.Q(tenant__isnull=True))
                    | models.Q(role="service_account")
                    | (
                        models.Q(role__in=["admin", "dispatcher", "agent", "driver", "controller"])
                        & models.Q(tenant__isnull=False)
                    )
                ),
                name="user_tenant_matches_role",
            ),
            # Un client sans e-mail ni téléphone serait un compte que personne
            # ne peut plus jamais retrouver ni authentifier.
            models.CheckConstraint(
                condition=(
                    ~models.Q(role="client")
                    | models.Q(email__isnull=False)
                    | ~models.Q(phone="")
                ),
                name="user_client_has_contact",
            ),
            # Le personnel n'a qu'une voie de connexion : l'e-mail et le mot de
            # passe. Sans adresse, le compte existe sans que personne ne puisse
            # s'y connecter.
            models.CheckConstraint(
                condition=(
                    ~models.Q(role__in=[
                        "admin", "dispatcher", "agent", "driver", "controller", "superadmin",
                    ])
                    | models.Q(email__isnull=False)
                ),
                name="user_staff_has_email",
            ),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    #: Rôles qui n'existent qu'au sein d'une compagnie.
    TENANT_SCOPED_ROLES = ("admin", "dispatcher", "agent", "driver", "controller")

    #: Rôles qui se connectent par e-mail et mot de passe. `SERVICE_ACCOUNT` en
    #: est exclu : ses comptes ne se connectent jamais, et rien ne garantit
    #: qu'un futur porteur technique ait une adresse.
    EMAIL_REQUIRED_ROLES = (*TENANT_SCOPED_ROLES, "superadmin")

    def clean(self):
        """Même doctrine que les contraintes DB, rejouée pour les formulaires.

        Les contraintes de base sont le filet de sécurité (elles tiennent face à
        un `bulk_create` ou du SQL direct) ; `clean()` est ce qui produit un
        message lisible dans l'admin au lieu d'une IntegrityError.
        """
        errors = {}

        if self.role == self.Role.SUPERADMIN and self.tenant is not None:
            errors["tenant"] = "Un superadmin TOUPAC n'est rattaché à aucune compagnie."

        elif self.role == self.Role.CLIENT:
            if self.tenant is not None:
                errors["tenant"] = (
                    "Un client TOUPAC n'est rattaché à aucune compagnie : il achète "
                    "chez plusieurs transporteurs avec le même compte."
                )
            if not self.email and not self.phone:
                errors["email"] = "Un client doit avoir au moins un email ou un téléphone."

        elif self.role in self.TENANT_SCOPED_ROLES and self.tenant is None:
            errors["tenant"] = "Ce rôle n'existe qu'au sein d'une compagnie : renseignez-la."

        # Le personnel se connecte par e-mail et mot de passe : sans e-mail, le
        # compte est créé mais personne ne pourra jamais s'y connecter. Le
        # client en est dispensé — il se connecte par code, e-mail ou téléphone.
        if self.role in self.EMAIL_REQUIRED_ROLES and not self.email:
            errors["email"] = "Ce rôle exige un email : c'est sa voie de connexion."

        # SERVICE_ACCOUNT : aucune règle, les deux cas sont légitimes
        # (platform-bot global sans tenant, bot de compagnie avec).

        if errors:
            raise ValidationError(errors)

    @classmethod
    def get_or_create_client(cls, email=None, phone=None, first_name="", last_name=""):
        """
        Récupère ou crée un utilisateur CLIENT global (tenant=None). Idempotent.

        Résolution par e-mail d'abord, puis par téléphone : un passager qui
        laisse son e-mail au chatbot web et son téléphone au chatbot WhatsApp
        converge vers un seul compte dès qu'il fournit les deux une fois.

        L'enrichissement ne remplace jamais une valeur déjà posée — il ne
        comble que les champs vides. Un appel entrant ne doit pas pouvoir
        réécrire l'e-mail d'un compte existant : ce serait une prise de contrôle
        de compte par simple collision de numéro.

        Retourne `(user, created)`, comme `get_or_create`.
        """
        if not email and not phone:
            raise ValueError("get_or_create_client exige au moins un email ou un téléphone.")

        user = None
        if email:
            user = cls.objects.filter(email=email, role=cls.Role.CLIENT).first()
        if user is None and phone:
            user = cls.objects.filter(phone=phone, role=cls.Role.CLIENT).first()

        if user is not None:
            updated = []
            for field, value in (
                ("email", email), ("phone", phone),
                ("first_name", first_name), ("last_name", last_name),
            ):
                if not value or getattr(user, field):
                    continue
                # Un identifiant déjà porté par quelqu'un d'autre n'est pas
                # recopié : l'appelant présente un e-mail et un téléphone qui
                # appartiennent à deux comptes distincts. Les fusionner est une
                # décision produit (avec vérification de propriété), pas quelque
                # chose qu'un helper doit faire dans le dos de l'utilisateur.
                # On laisse donc les comptes séparés plutôt que de planter.
                if field in ("email", "phone") and cls._identifier_taken(field, value, user.pk):
                    continue
                setattr(user, field, value)
                updated.append(field)
            if updated:
                user.save(update_fields=updated)
            return user, False

        # Création : un identifiant déjà pris rend le compte impossible. On le
        # dit clairement plutôt que de laisser remonter une IntegrityError, que
        # l'appelant ne saurait pas distinguer d'une panne.
        if email and cls._identifier_taken("email", email):
            raise ValueError(
                f"L'email {email} est déjà utilisé par un compte existant "
                "qui n'est pas un client."
            )
        if phone and cls._identifier_taken("phone", phone):
            raise ValueError(f"Le téléphone {phone} est déjà utilisé par un autre client.")

        user = cls(
            email=email or None,  # "" violerait l'unicité au deuxième client sans e-mail
            phone=phone or "",
            first_name=first_name, last_name=last_name,
            tenant=None, role=cls.Role.CLIENT,
            is_active=True, is_staff=False, is_superuser=False,
        )
        user.set_unusable_password()
        user.save()
        return user, True

    @classmethod
    def _identifier_taken(cls, field, value, exclude_pk=None):
        """
        Un autre compte porte-t-il déjà cet identifiant ?

        L'e-mail est unique tous rôles confondus ; le téléphone ne l'est
        qu'entre clients — un chauffeur peut partager son numéro avec le compte
        client du même humain, et cette collision-là est légitime.
        """
        queryset = cls.objects.filter(**{field: value})
        if field == "phone":
            queryset = queryset.filter(role=cls.Role.CLIENT)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @classmethod
    def get_or_create_platform_bot(cls):
        """
        Compte technique unique portant les requêtes des clés plateforme. Idempotent.

        Là où un compte de service tenant (`api-bot@<slug>.internal`) existe par
        compagnie, celui-ci est global : `tenant=None`, comme les superadmins,
        parce qu'une `PlatformCredential` sert tous les tenants abonnés et que le
        tenant courant change à chaque requête.

        Il n'existe que pour satisfaire `IsAuthenticated` et donner un
        `request.user` réel aux vues métier qui lisent `.email` ou `.role`. Il ne
        peut pas s'authentifier (mot de passe inutilisable), n'entre pas dans le
        back-office et ne porte aucune permission Django : le contrôle d'accès
        d'une requête plateforme passe entièrement par les scopes de la clé.
        """
        bot = cls.objects.filter(email=PLATFORM_BOT_EMAIL).first()
        if bot is not None:
            return bot

        bot = cls(
            email=PLATFORM_BOT_EMAIL,
            first_name="Platform", last_name="Bot",
            tenant=None, role=cls.Role.SERVICE_ACCOUNT,
            is_active=True, is_staff=False, is_superuser=False,
        )
        bot.set_unusable_password()
        bot.save()
        return bot


#: Porteur technique global des requêtes plateforme. `.internal` est un TLD
#: réservé (ICANN, 2024) : non routable, aucune adresse n'y reçoit de courrier.
PLATFORM_BOT_EMAIL = "platform-bot@toupac.internal"


# ─── API Credentials ───

class ApiCredential(TimestampMixin, models.Model):
    id = UUIDv7Field()
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_credentials")
    # null : la clé survit à la suppression de son porteur (SET_NULL).
    # blank : full_clean() ne doit pas exiger un porteur que la DB accepte
    # d'omettre — la contrainte « porteur obligatoire à l'émission » est
    # portée par ApiCredentialCreateForm et par ApiKeyAuthentication.
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="api_credentials",
    )
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


# ─── Platform Credentials (services plateforme TOUPAC) ───

#: Préfixe des clés plateforme. Volontairement distinct de `tpc_` (clés tenant)
#: pour qu'un secret égaré se classe au premier coup d'œil et pour que le backend
#: d'auth plateforme puisse rendre la main sans requête SQL sur une clé tenant.
PLATFORM_KEY_PREFIX = "tpc_platform_"

#: Marge minimale entre maintenant et `expires_at` à l'émission. Émettre une clé
#: qui expire dans l'heure est toujours une erreur de saisie, jamais une intention.
PLATFORM_MIN_LIFETIME = timedelta(hours=12)

#: Durée de vie par défaut proposée à l'émission (rotation forcée).
PLATFORM_DEFAULT_LIFETIME = timedelta(days=90)


class PlatformCredential(TimestampMixin, models.Model):
    """
    Credential d'un service plateforme TOUPAC (chatbot BI, futures apps).

    Distincte d'`ApiCredential` (une clé par tenant, émise par l'admin du
    tenant). Pas de FK `tenant` : une même clé sert tous les tenants abonnés au
    service, et le tenant visé est indiqué par `X-Tenant-ID` sur chaque requête.
    Émission et révocation réservées au superadmin TOUPAC.
    """

    id = UUIDv7Field()
    name = models.CharField("Nom", max_length=100, help_text="Ex : « Chatbot Toupac BI production »")
    platform_service = models.CharField(
        "Service plateforme", max_length=50,
        help_text="Slug déclaré dans iam/platform_services.py (ex : chatbot-bi).",
    )
    key_prefix = models.CharField("Préfixe clé", max_length=24, unique=True, db_index=True)
    key_hash = models.CharField("Hash clé", max_length=200)
    platform_scopes = models.JSONField("Scopes plateforme", default=list, blank=True)
    allowed_ips = models.JSONField(
        "IP autorisées (CIDR)", default=list, blank=True,
        help_text="Liste de CIDR autorisés, ex : [\"52.34.10.5/32\", \"10.0.0.0/24\"]. "
                  "Liste vide = accepté uniquement en DEBUG.",
    )
    is_active = models.BooleanField("Active", default=True)
    expires_at = models.DateTimeField(
        "Expire le", help_text="Rotation forcée. Défaut à la création : +90 jours.",
    )
    last_used_at = models.DateTimeField("Dernier usage", null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="platform_credentials_issued", verbose_name="Émise par",
    )

    class Meta:
        db_table = "iam_platform_credentials"
        verbose_name = "Clé plateforme"
        verbose_name_plural = "Clés plateforme"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    def clean(self):
        from iam.platform_scopes import validate_platform_scopes
        from iam.platform_services import is_valid_platform_service

        errors = {}

        if not is_valid_platform_service(self.platform_service):
            errors["platform_service"] = (
                f"Service plateforme inconnu : {self.platform_service!r}. "
                "Les services sont déclarés dans iam/platform_services.py."
            )

        unknown = validate_platform_scopes(self.platform_scopes)
        if unknown:
            errors["platform_scopes"] = f"Scope(s) plateforme inconnu(s) : {', '.join(unknown)}"

        # Contrôlé seulement à la création : durcir une clé existante dont
        # l'expiration approche empêcherait de la désactiver depuis l'admin.
        if self._state.adding and self.expires_at is not None:
            if self.expires_at < timezone.now() + PLATFORM_MIN_LIFETIME:
                errors["expires_at"] = (
                    "Une clé plateforme doit être valide au moins 12 heures après son "
                    "émission. Utilisez la valeur par défaut (+90 jours) sauf raison contraire."
                )

        for cidr in self.allowed_ips or []:
            try:
                ip_network(cidr, strict=False)
            except ValueError:
                errors.setdefault("allowed_ips", []).append(f"CIDR invalide : {cidr!r}")

        if errors:
            raise ValidationError(errors)

    def has_platform_scope(self, scope_name):
        """True si le scope est accordé. Pas de super-scope côté plateforme."""
        return scope_name in (self.platform_scopes or [])

    def is_usable(self):
        return self.is_active and self.expires_at > timezone.now()

    def allows_ip(self, ip, *, debug=False):
        """
        True si `ip` est couverte par l'allowlist.

        Une allowlist vide n'ouvre l'accès qu'en DEBUG : en production elle
        signale une clé mal configurée, et laisser passer serait exactement la
        mitigation qu'on croyait avoir posée. Le refus est donc le défaut.
        """
        if not self.allowed_ips:
            return bool(debug)
        try:
            candidate = ip_address(ip)
        except ValueError:
            return False
        for cidr in self.allowed_ips:
            try:
                if candidate in ip_network(cidr, strict=False):
                    return True
            except ValueError:
                # CIDR corrompu en base : ignoré plutôt que fatal, il ne doit
                # pas rendre la clé inutilisable au point de bloquer sa rotation.
                continue
        return False

    @property
    def days_until_expiry(self):
        return (self.expires_at - timezone.now()).days

    @classmethod
    def issue(cls, name, platform_service, platform_scopes, allowed_ips=None,
              expires_at=None, created_by=None):
        """
        Crée une clé plateforme et retourne (credential, clé_en_clair).

        La clé en clair n'est ni stockée ni réaffichable : seul son hash l'est.
        C'est le seul moment où l'appelant peut la transmettre.
        """
        from django.contrib.auth.hashers import make_password

        # 13 caractères de préfixe fixe + 8 hex = 21, d'où le max_length=24 du
        # champ. Le préfixe est un identifiant public, pas un secret : son
        # entropie sert à éviter les collisions, pas à résister à une attaque.
        prefix = f"{PLATFORM_KEY_PREFIX}{secrets.token_hex(4)}"
        secret = secrets.token_urlsafe(32)
        credential = cls(
            name=name,
            platform_service=platform_service,
            platform_scopes=list(platform_scopes),
            allowed_ips=list(allowed_ips or []),
            key_prefix=prefix,
            key_hash=make_password(secret),
            expires_at=expires_at or (timezone.now() + PLATFORM_DEFAULT_LIFETIME),
            created_by=created_by,
        )
        credential.full_clean(exclude=["created_by"])
        credential.save()
        return credential, f"{prefix}.{secret}"


class TenantSubscription(models.Model):
    """
    Abonnement d'un tenant à un service plateforme.

    C'est la seule autorisation qui ouvre les données d'un tenant à une
    `PlatformCredential`. Créé par superadmin TOUPAC — un tenant ne s'abonne pas
    lui-même, l'abonnement relève du contrat commercial.
    """

    id = UUIDv7Field()
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="platform_subscriptions", verbose_name="Tenant",
    )
    platform_service = models.CharField("Service plateforme", max_length=50)
    is_active = models.BooleanField("Actif", default=True)
    granted_at = models.DateTimeField("Accordé le", auto_now_add=True)
    revoked_at = models.DateTimeField("Révoqué le", null=True, blank=True)
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="subscriptions_granted", verbose_name="Accordé par",
    )
    notes = models.TextField("Notes", blank=True)

    class Meta:
        db_table = "iam_tenant_subscriptions"
        verbose_name = "Abonnement plateforme"
        verbose_name_plural = "Abonnements plateforme"
        ordering = ["tenant__name", "platform_service"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform_service"],
                name="unique_tenant_service_subscription",
            ),
        ]

    def __str__(self):
        return f"{self.tenant} → {self.platform_service}"

    def clean(self):
        from iam.platform_services import is_valid_platform_service

        if not is_valid_platform_service(self.platform_service):
            raise ValidationError({
                "platform_service": (
                    f"Service plateforme inconnu : {self.platform_service!r}. "
                    "Les services sont déclarés dans iam/platform_services.py."
                ),
            })


class PlatformAuditLog(models.Model):
    """
    Trace d'un appel API porté par une `PlatformCredential`.

    Une entrée par requête, succès comme échec : un refus d'IP ou un accès à un
    tenant non abonné est précisément ce qu'on veut voir passer. La volumétrie
    justifie un BigAutoField plutôt qu'un UUID (cf. `tracking.Position`).
    """

    id = models.BigAutoField(primary_key=True)
    credential = models.ForeignKey(
        PlatformCredential, on_delete=models.CASCADE, related_name="audit_logs", verbose_name="Clé",
    )
    tenant_context = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="platform_audit_logs", verbose_name="Tenant visé",
        help_text="Tenant résolu depuis X-Tenant-ID. Vide pour les endpoints globaux.",
    )
    endpoint = models.CharField("Endpoint", max_length=200)
    method = models.CharField("Méthode", max_length=10)
    ip = models.GenericIPAddressField("IP source")
    user_agent = models.CharField("User-Agent", max_length=500, blank=True)
    status_code = models.IntegerField("Code HTTP")
    latency_ms = models.IntegerField("Latence (ms)", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "iam_platform_audit_logs"
        verbose_name = "Appel plateforme"
        verbose_name_plural = "Appels plateforme"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["credential", "-created_at"]),
            models.Index(fields=["tenant_context", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.method} {self.endpoint} → {self.status_code}"


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
