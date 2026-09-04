"""
TOUPAC — Settings de base (partagés dev/staging/prod).
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-in-prod")

INSTALLED_APPS = [
    # Admin UI (unfold doit être AVANT django.contrib.admin)
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",          # GeoDjango
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "guardian",
    # TOUPAC modules
    "core",
    "iam",
    "fleet",
    "geo",
    "workflow",
    "voyage",
    "colis",
    "billing",
    "tracking",
    "notifications",
    "developers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Database ───
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DB_NAME", "toupac"),
        "USER": os.environ.get("DB_USER", "toupac"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "toupac"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# ─── Cache (Redis) ───
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    }
}

# ─── Auth ───
AUTH_USER_MODEL = "iam.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "guardian.backends.ObjectPermissionBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── REST Framework ───
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # La clé API d'abord : elle s'identifie par son propre header et
        # rend la main aux suivants s'il est absent.
        "iam.api_key_authentication.ApiKeyAuthentication",
        # JWTAuthentication + vérification du denylist des access tokens
        # révoqués au logout (cf. iam/authentication.py).
        "iam.authentication.DenylistJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        # Globale et non par vue : un endpoint qui ne déclare pas de scope
        # doit être fermé aux clés API, pas ouvert par défaut. Sans effet
        # sur les utilisateurs JWT ou session.
        "iam.permissions.HasApiScope",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "10/minute",
        "batch_sync": "20/minute",
        "payment_initiate": "30/minute",
        "tenant_burst": "100/minute",
        # Rate limiting par clé API (cf. iam/throttles.py)
        "api_key_default": "1000/hour",
        "api_key_admin": "10000/hour",
    },
    "EXCEPTION_HANDLER": "core.exceptions.toupac_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ─── Documentation API (drf-spectacular) ───
SPECTACULAR_SETTINGS = {
    "TITLE": "TOUPAC API",
    "DESCRIPTION": """
API du Transport Management System TOUPAC.

**Modules :**
- **IAM** — Authentification JWT, gestion utilisateurs
- **Fleet** — Véhicules, chauffeurs, flottes
- **Geo** — Lieux (PostGIS), zones de service
- **Voyage** — Routes, horaires, voyages passagers, réservations, contrôle embarquement
- **Colis** — Commandes de livraison, colis, dispatch, preuve de livraison
- **Billing** — Tarification, factures, paiement mobile money (Wave, Orange Money)
- **Tracking** — Positions GPS, géofences, liens de suivi publics
- **Notifications** — Templates, envoi SMS/WhatsApp/Push
- **Workflow** — Machine à états configurable par compagnie

**Authentification :** Bearer JWT (header `Authorization: Bearer <token>`)

**Multi-tenant :** Chaque requête est automatiquement scopée au tenant de l'utilisateur connecté.
""",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "TAGS": [
        {"name": "Auth", "description": "Authentification JWT (login, refresh, logout)"},
        {"name": "Fleet", "description": "Gestion de la flotte de véhicules et chauffeurs"},
        {"name": "Geo", "description": "Lieux et zones géographiques (PostGIS)"},
        {"name": "Voyage", "description": "Transport de passagers — routes, voyages, réservations"},
        {"name": "Colis", "description": "Livraison de colis — commandes, dispatch, POD"},
        {"name": "Billing", "description": "Facturation et paiement mobile money"},
        {"name": "Tracking", "description": "Suivi GPS temps réel et géofences"},
        {"name": "Notifications", "description": "Envoi de notifications multi-canal"},
        {"name": "Workflow", "description": "Machine à états configurable"},
    ],
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayOperationId": False,
        "filter": True,
    },
    "SECURITY": [{"Bearer": []}],
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "Bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
}

# ─── JWT (simplejwt) — pattern validé Sprint 2 §4.19 ───
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "iam.serializers.ToupacTokenObtainSerializer",
}

# ─── Intouch (agrégateur mobile money) ───
INTOUCH_LOGIN_AGENT = os.environ.get("INTOUCH_LOGIN_AGENT", "SANDBOX_LOGIN")
INTOUCH_PASSWORD_AGENT = os.environ.get("INTOUCH_PASSWORD_AGENT", "SANDBOX_PASSWORD")
INTOUCH_PARTNER_ID = os.environ.get("INTOUCH_PARTNER_ID", "SANDBOX_PARTNER")

# ─── QR billets (voyage.services.qr_jwt) — RS256 ───
# Clé privée : jamais de valeur par défaut. Vide ⇒ qr_jwt génère une keypair
# éphémère en mémoire (dev uniquement, cf. le warning au premier appel).
TOUPAC_QR_PRIVATE_KEY_PEM = os.environ.get("TOUPAC_QR_PRIVATE_KEY_PEM", "")
# Clé publique : vide ⇒ qr_jwt retombe sur voyage/keys/qr_public.pem, puis
# sur une clé dérivée de la privée, avant de renoncer (qr_public_key: null).
TOUPAC_QR_PUBLIC_KEY_PEM = os.environ.get("TOUPAC_QR_PUBLIC_KEY_PEM", "")

# ─── Celery ───
from celery.schedules import crontab

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Dakar"

CELERY_BEAT_SCHEDULE = {
    # Purge des positions GPS > 90 jours (RGPD géoloc) — tous les jours à 3h
    "purge-old-positions": {
        "task": "tracking.tasks.purge_old_positions",
        "schedule": crontab(hour=3, minute=0),
    },
    # Alerte documents véhicules expirant dans 30 jours — tous les lundis à 8h
    "check-expiring-documents": {
        "task": "fleet.tasks.check_expiring_documents",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),
    },
}

# ─── Channels ───
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [os.environ.get("REDIS_URL", "redis://localhost:6379/2")]},
    },
}

# ─── i18n ───
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

# ─── Static & Media ───
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Unfold Admin ───
UNFOLD = {
    "SITE_TITLE": "TOUPAC",
    "SITE_HEADER": "TOUPAC Admin",
    "SITE_SYMBOL": "directions_bus",
    "COLORS": {
        "primary": {
            "50": "232 245 233",
            "100": "200 230 201",
            "200": "165 214 167",
            "300": "129 199 132",
            "400": "102 187 106",
            "500": "15 110 86",
            "600": "67 160 71",
            "700": "56 142 60",
            "800": "46 125 50",
            "900": "27 94 32",
        },
    },
    "SIDEBAR": {
        "navigation": [
            {
                "title": "Tableau de bord",
                "icon": "dashboard",
                "items": [
                    {"title": "Tableau de bord", "link": "/admin/"},
                ],
            },
            {
                "title": "Organisation",
                "icon": "corporate_fare",
                "items": [
                    {"title": "Tenants", "link": "/admin/iam/tenant/"},
                    {"title": "Utilisateurs", "link": "/admin/iam/user/"},
                ],
            },
            {
                "title": "Flotte",
                "icon": "directions_bus",
                "items": [
                    {"title": "Types de véhicules", "link": "/admin/fleet/vehicletype/"},
                    {"title": "Véhicules", "link": "/admin/fleet/vehicle/"},
                    {"title": "Chauffeurs", "link": "/admin/fleet/driver/"},
                ],
            },
            {
                "title": "Géographie",
                "icon": "map",
                "items": [
                    {"title": "Lieux", "link": "/admin/geo/place/"},
                    {"title": "Zones", "link": "/admin/geo/zone/"},
                ],
            },
            {
                "title": "Voyages",
                "icon": "airline_seat_recline_normal",
                "items": [
                    {"title": "Routes", "link": "/admin/voyage/route/"},
                    {"title": "Horaires", "link": "/admin/voyage/schedule/"},
                    {"title": "Voyages", "link": "/admin/voyage/trip/"},
                    {"title": "Réservations", "link": "/admin/voyage/reservation/"},
                    {"title": "Passagers", "link": "/admin/voyage/passenger/"},
                    {"title": "Plans de sièges", "link": "/admin/voyage/seatmap/"},
                    {"title": "Politiques bagages", "link": "/admin/voyage/luggagepolicy/"},
                    {"title": "Contrôleurs", "link": "/admin/voyage/controller/"},
                ],
            },
            {
                "title": "Colis & Livraison",
                "icon": "inventory_2",
                "items": [
                    {"title": "Commandes", "link": "/admin/colis/order/"},
                    {"title": "Colis", "link": "/admin/colis/parcel/"},
                    {"title": "Tâches livraison", "link": "/admin/colis/deliverytask/"},
                ],
            },
            {
                "title": "Facturation",
                "icon": "payments",
                "items": [
                    {"title": "Grilles tarifaires", "link": "/admin/billing/pricelist/"},
                    {"title": "Factures", "link": "/admin/billing/invoice/"},
                    {"title": "Paiements", "link": "/admin/billing/payment/"},
                ],
            },
            {
                "title": "Tracking GPS",
                "icon": "location_on",
                "items": [
                    {"title": "Positions", "link": "/admin/tracking/position/"},
                    {"title": "Géofences", "link": "/admin/tracking/geofence/"},
                    {"title": "Liens de suivi", "link": "/admin/tracking/trackinglink/"},
                ],
            },
            {
                "title": "Notifications",
                "icon": "notifications",
                "items": [
                    {"title": "Templates", "link": "/admin/notifications/notificationtemplate/"},
                    {"title": "Historique", "link": "/admin/notifications/notificationlog/"},
                ],
            },
            {
                "title": "Workflow",
                "icon": "account_tree",
                "items": [
                    {"title": "Définitions", "link": "/admin/workflow/workflowdefinition/"},
                ],
            },
        ],
    },
}
