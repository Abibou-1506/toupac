"""
TOUPAC IAM — Scopes des clés API.

Source de vérité unique : le portail développeur et la validation du modèle
lisent tous deux ce dictionnaire. Un scope vaut `{domaine}:{action}`, où
l'action est `read` ou `write` — `write` n'implique pas `read`, une clé qui
doit lire et écrire porte les deux.

`admin:*` est un super-scope : il satisfait n'importe quelle vérification.
Réservé aux intégrations SI internes du client (ERP maison) ; il ne doit
jamais être accordé à un partenaire externe comme le chatbot.
"""

ADMIN_SCOPE = "admin:*"

AVAILABLE_SCOPES = {
    # Voyage
    "voyage:read": "Lire routes, horaires, voyages, réservations",
    "voyage:write": "Créer/modifier réservations, transitions de voyage",
    # Colis
    "colis:read": "Lire commandes, colis, tâches de livraison",
    "colis:write": "Créer/modifier commandes, marquer les preuves de livraison",
    # Fleet
    "fleet:read": "Lire véhicules, chauffeurs, documents",
    "fleet:write": "Créer/modifier véhicules, assignations",
    # Billing
    "billing:read": "Lire factures, paiements, grilles tarifaires",
    "billing:write": "Créer factures, initier paiements",
    # Tracking
    "tracking:read": "Lire positions GPS, géofences, événements",
    "tracking:write": "Créer géofences, liens de suivi",
    # Notifications
    "notifications:read": "Lire logs de notifications, templates",
    "notifications:write": "Envoyer des notifications ad-hoc, créer des templates",
    # IAM
    "iam:read": "Lire les utilisateurs du tenant et les clés API",
    "iam:write": "Créer/modifier des utilisateurs (usage restreint)",
    # Super-scope
    ADMIN_SCOPE: "Accès complet au tenant, tous domaines",
}

#: Actions DRF considérées comme de la lecture.
READ_ACTIONS = frozenset({"list", "retrieve"})


def scope_for_action(domain, action):
    """Retourne le scope attendu pour une action DRF sur un domaine."""
    return f"{domain}:{'read' if action in READ_ACTIONS else 'write'}"


def validate_scopes(scopes):
    """Retourne la liste des scopes inconnus parmi ceux fournis."""
    return [scope for scope in scopes or [] if scope not in AVAILABLE_SCOPES]


def get_scope_choices():
    """Choix pour un champ de formulaire — même source que le portail développeur."""
    return [(name, f"{name} — {description}") for name, description in AVAILABLE_SCOPES.items()]
