"""
TOUPAC IAM — Services plateforme déclarés.

Un « service plateforme » est une intégration *de la plateforme, pour tous les
tenants* (chatbot Toupac BI, future app mobile TOUPAC officielle, adaptateur
Toupac CRM). Il s'oppose à l'intégration *du tenant, par le tenant*, servie par
`ApiCredential` — voir docs/design/platform-credentials.md.

Chaque service reçoit une `PlatformCredential` unique, émise et rotée par
superadmin TOUPAC. Un tenant s'abonne à un service via `TenantSubscription` ;
le service accède alors à ses données en passant `X-Tenant-ID: <slug>`.

Source de vérité en code, pas en base : la liste des services est une décision
de conception (chaque ajout s'accompagne d'un contrat, de scopes et d'une revue
sécurité), pas une donnée d'exploitation qu'un opérateur saisit à la volée.
"""

PLATFORM_SERVICES = {
    "chatbot-bi": {
        "label": "Chatbot Toupac BI",
        "description": "Assistant conversationnel maintenu par le partenaire externe",
        "default_scopes": [
            "platform:voyage:read", "platform:colis:read",
            "platform:tracking:read", "platform:billing:read",
            "platform:notifications:read", "platform:global:read",
        ],
    },
    # Ajouter d'autres services au fur et à mesure (toupac-crm, mobile-app…).
}


def is_valid_platform_service(slug: str) -> bool:
    return slug in PLATFORM_SERVICES


def get_platform_service(slug: str) -> dict:
    if slug not in PLATFORM_SERVICES:
        raise KeyError(f"Unknown platform service: {slug}")
    return PLATFORM_SERVICES[slug]


def get_platform_service_choices():
    """Choix pour un champ de formulaire — même source que le portail développeur."""
    return [(slug, spec["label"]) for slug, spec in PLATFORM_SERVICES.items()]
