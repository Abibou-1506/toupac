"""TOUPAC Voyage — Exceptions du protocole offline-sync."""


class EventRejected(Exception):
    """
    Rejet d'un event offline avec rollback complet de ses side-effects.

    Un handler qui lève cette exception fait rollback du savepoint : rien de ce
    qu'il a écrit n'est conservé. Pour un rejet qui DOIT garder ses side-effects
    (typiquement l'anomalie auto-détectée qui motive le rejet), le handler
    retourne à la place un dict {"status": "rejected", "rejection_reason": ...}.
    """
