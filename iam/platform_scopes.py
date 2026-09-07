"""
TOUPAC IAM — Scopes plateforme, portés par une `PlatformCredential`.

Distincts des scopes tenant (`iam.scopes.AVAILABLE_SCOPES`) et jamais mélangés :
une `ApiCredential` porte des scopes tenant, une `PlatformCredential` porte des
scopes plateforme. Le préfixe `platform:` rend la distinction lisible au grep et
empêche qu'un scope accordé d'un côté satisfasse une vérification de l'autre.

Deux règles de doctrine, tenues par les tests :

- **Pas de super-scope `platform:*`.** `admin:*` existe côté tenant pour
  l'outillage interne TOUPAC ; aucun équivalent ici, parce que les porteurs de
  clés plateforme sont des partenaires externes. Chaque clé est émise avec un
  ensemble explicite de scopes.
- **Pas de scope en écriture en V1.** Le chatbot traduit du langage naturel en
  appels API : lui ouvrir l'écriture exposerait des effets réels (push chauffeur,
  SMS payant) au bout d'un prompt qu'on ne maîtrise pas. Décision produit, pas
  limitation technique — voir docs/design/platform-credentials.md.
"""

#: Scope des endpoints sans contexte tenant. Le seul qui refuse `X-Tenant-ID`.
GLOBAL_SCOPE = "platform:global:read"

#: Scope des endpoints qui répondent au nom d'un client. Ils exigent
#: `X-Acting-User-Email` (ou `X-Acting-User-Phone`) : sans client désigné, il
#: n'y a pas de « mes réservations » à servir.
CUSTOMER_SCOPE = "platform:customer:read"

PLATFORM_AVAILABLE_SCOPES = {
    "platform:voyage:read": "Lecture des données voyage (routes, réservations, sièges)",
    "platform:voyage:write": "Écriture voyage (réservations, annulations) au nom d'un client",
    "platform:colis:read": "Lecture des données colis (commandes, livraisons)",
    "platform:colis:write": "Écriture colis (commandes, mises à jour) au nom d'un client",
    "platform:tracking:read": "Lecture des positions GPS",
    "platform:billing:read": "Lecture de la facturation",
    "platform:billing:write": "Écriture facturation (paiements initiés, remboursements)",
    "platform:notifications:read": "Lecture du centre d'alertes",
    CUSTOMER_SCOPE: "Lecture de l'espace d'un client (X-Acting-User-Email requis)",
    GLOBAL_SCOPE: "Endpoints globaux (liste des compagnies, santé de la clé) — refuse X-Tenant-ID",
    # Toujours pas de super-scope `platform:*` : chaque clé porte une liste
    # explicite. Toujours pas de `platform:notifications:emit` non plus —
    # émettre une notification produit un effet réel (vibration d'un
    # téléphone, SMS facturé) et reste réservé au code métier interne.
}


def get_platform_scope_choices():
    return [(name, f"{name} — {description}") for name, description in PLATFORM_AVAILABLE_SCOPES.items()]


def validate_platform_scopes(scopes):
    """Retourne la liste des scopes inconnus parmi ceux fournis."""
    return [scope for scope in scopes or [] if scope not in PLATFORM_AVAILABLE_SCOPES]


def is_tenant_endpoint_scope(scope: str) -> bool:
    """Un scope tenant exige un `X-Tenant-ID`."""
    return scope != GLOBAL_SCOPE


def is_global_endpoint_scope(scope: str) -> bool:
    return scope == GLOBAL_SCOPE


def requires_acting_user(scope: str) -> bool:
    """Ce scope n'a de sens qu'avec un client désigné par en-tête."""
    return scope == CUSTOMER_SCOPE


def platform_scope_for_domain(domain: str, *, write: bool = False) -> str:
    """
    Traduit un domaine de scope tenant en scope plateforme.

    Les ViewSets métier déclarent déjà `api_scope_domain = "voyage"` pour les
    clés tenant. Les réannoter un par un pour la plateforme dupliquerait la même
    information et laisserait dériver les deux listes ; on dérive donc le scope
    plateforme du domaine déjà déclaré.

    Un domaine sans scope d'écriture déclaré produit une chaîne qui n'est dans
    aucune clé : le refus est automatique, sans liste d'exceptions à maintenir.
    """
    return f"platform:{domain}:{'write' if write else 'read'}"
