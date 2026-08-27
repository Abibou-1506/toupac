"""
TOUPAC Voyage — Handlers d'events offline.

Chaque handler a la signature `handler(event, tenant, session) -> dict` et est
exécuté par le BatchEventProcessor dans un savepoint dédié :

- retourner {"status": "accepted", ...} valide l'event et ses écritures ;
- retourner {"status": "rejected", "rejection_reason": ...} rejette l'event
  mais CONSERVE ses écritures (cas typique : l'anomalie qui motive le rejet) ;
- lever EventRejected rejette l'event et ANNULE toutes ses écritures.
"""
