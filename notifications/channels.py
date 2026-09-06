"""TOUPAC Notifications — Canaux de diffusion (miroir import-safe du modèle).

Doublon assumé de `NotificationTemplate.Channel` : le catalogue doit rester
importable sans registre d'applications Django prêt. `test_catalog.py` vérifie
que les deux enums ne divergent jamais.

`StrEnum` pour la même raison que `Priority` : `str(Channel.PUSH)` doit valoir
"push", pas "Channel.PUSH".
"""
from enum import StrEnum


class Channel(StrEnum):
    PUSH = "push"
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
