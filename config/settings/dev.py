"""TOUPAC — Dev settings (SQLite fallback si pas de PostgreSQL)."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True

# Fallback SQLite si pas de PostGIS dispo en dev local
import shutil

if not shutil.which("pg_config"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        # « toupac » et non « notifications » : le code écrit dans
        # `toupac.notifications`, `toupac.iam.otp`, `toupac.iam.platform`. La
        # hiérarchie des loggers Python suit les points — `toupac.notifications`
        # remonte vers `toupac`, jamais vers `notifications`, qui en est un
        # frère. Déclarer la racine « toupac » capte donc tout le projet.
        "toupac": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
