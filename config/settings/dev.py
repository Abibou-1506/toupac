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
