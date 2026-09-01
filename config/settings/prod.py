"""TOUPAC — Prod settings (cloud souverain SN)."""
import os

from .base import *

DEBUG = False
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

# Security
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# CSRF trusted origins (pour l'admin derrière Caddy)
CSRF_TRUSTED_ORIGINS = [
    f"https://{host.strip()}" for host in ALLOWED_HOSTS if host.strip()
]

# Static files (collectées dans le volume Docker)
STATIC_ROOT = "/app/staticfiles"
MEDIA_ROOT = "/app/media"

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "toupac": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
