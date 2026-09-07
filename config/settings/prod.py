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

# ─── E-mails ───
# SMTP réel. Les quatre variables ci-dessous sont à renseigner dans `.env.prod`
# avant la première utilisation : tant qu'elles manquent, `EmailSmtpProvider`
# lève à chaque envoi, la politique de réessai du canal e-mail s'applique
# (trois tentatives espacées), et l'envoi finit tracé en échec.
#
# Cet échec visible est voulu : il vaut mieux qu'un envoi qui se déclare réussi
# sans que personne ne reçoive rien — ce que faisait le provider console jusqu'à
# ce ticket.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"

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
