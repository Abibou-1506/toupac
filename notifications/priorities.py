"""TOUPAC Notifications — Priorités d'événement (charte TOUPAC ONE).

Côté catalogue uniquement : ces valeurs sont recopiées dans
`Notification.priority` par le service (Ticket B). Le modèle porte ses propres
`TextChoices` pour que l'admin affiche des libellés — l'enum ici reste
import-safe (aucun modèle Django chargé), ce qui permet au catalogue d'être
importé très tôt.

`StrEnum` et non `(str, Enum)` : avec ce dernier, `str(Priority.CRITICAL)` vaut
"Priority.CRITICAL" et non "critical" — valeur qui finirait telle quelle en base
au premier `Notification(priority=...)` du Ticket B.
"""
from enum import StrEnum


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
