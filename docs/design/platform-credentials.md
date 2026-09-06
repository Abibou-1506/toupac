# PlatformCredential — Note de design

_Rédigé le 6 sept 2026 en réponse à une question produit sur l'onboarding
de l'équipe chatbot Toupac BI._
_Statut : proposition, à valider par le lead + confrontation avec l'équipe
chatbot avant implémentation._

## Contexte et problème

TOUPAC a récemment livré un système de clés API multi-tenant
(`ApiCredential`) : chaque compagnie de transport (Sahel Express, Dem Dikk,
etc.) émet ses propres clés depuis son admin Django, avec des scopes
explicites. Ce modèle est correct pour le cas générique — une compagnie
qui veut brancher son ERP maison, son propre CRM, son application privée.

Ce modèle n'est **pas** adapté au chatbot Toupac BI, développé par une
équipe externe partenaire. Le chatbot est **un service central de la
plateforme**, pas une intégration privée d'une compagnie. Il présente
des propriétés différentes du cas générique :

- Livré comme feature de la plateforme TOUPAC, pas comme intégration
  privée du tenant.
- Une seule équipe, un seul codebase, une seule relation contractuelle
  pour tous les tenants.
- Doit fonctionner immédiatement dès qu'un nouveau tenant existe et
  qu'il est abonné au service.
- L'équipe chatbot ne peut pas raisonnablement stocker et gérer 50+
  secrets distincts (un par tenant) à mesure que la plateforme grandit.

Concrètement, forcer le chatbot à consommer une `ApiCredential` par
tenant obligerait à :

1. Attendre qu'un admin de chaque nouvelle compagnie génère une clé.
2. Transmettre le secret de la compagnie vers l'équipe chatbot externe
   (partage de secrets entre organisations distinctes — à éviter).
3. Redéployer / re-configurer le chatbot à chaque onboarding.
4. Gérer la révocation à froid par le tenant sans coordination.

## Deux types d'intégrations à distinguer

Il faut poser un vocabulaire clair pour raisonner sur les modèles d'accès.

**Type 1 — Intégration « du tenant, par le tenant »**

Le tenant est propriétaire de l'intégration. Il l'a demandée, il la
maintient, il la révoque. Exemples :

- L'ERP maison de Sahel Express.
- Une application mobile custom que Dem Dikk développe pour ses agents.
- Un connecteur Sage installé chez le tenant.

Modèle d'accès : `ApiCredential` — une clé par tenant, tenant fixe côté
clé, émission et révocation par l'admin du tenant. **Modèle en place et
correct pour ce cas.**

**Type 2 — Intégration « de la plateforme, pour tous les tenants »**

TOUPAC (ou un partenaire mandaté) fournit un service qui accède aux
données de tous les tenants abonnés. Exemples :

- Chatbot Toupac BI (partenaire externe).
- Future application mobile TOUPAC officielle multi-tenant.
- Future intégration Business Intelligence tiers.
- Adaptateur Toupac CRM lui-même (Sage / Odoo maintenu par TOUPAC).

Modèle d'accès : **nouveau — `PlatformCredential`**. Une clé pour le
service, pas pour un tenant. Émission et révocation par superadmin
TOUPAC uniquement. Le tenant cible est indiqué par requête.

## Solution proposée : `PlatformCredential` + `X-Tenant-ID`

### Modèle produit

Deux nouveaux concepts.

**`PlatformCredential`** — credential d'un service plateforme.

- Pas de FK `tenant` (contrairement à `ApiCredential`).
- `name` (str) — identifiant humain (« Chatbot Toupac BI production »).
- `platform_scopes` (JSONField list) — scopes plateforme distincts des
  scopes tenant : `platform:voyage:read`, `platform:colis:read`,
  `platform:notifications:read`, etc.
- `key_prefix` + `key_hash` (identique à `ApiCredential`).
- `allowed_ips` (JSONField list de CIDR) — allowlist IP, requête depuis
  une autre IP = 403.
- `expires_at` (obligatoire, par défaut +90 jours) — rotation forcée.
- `is_active` (bool).
- Émise **uniquement par superadmin TOUPAC** via un admin dédié.

**`TenantSubscription`** — mapping tenant × service plateforme.

- `tenant` (FK).
- `platform_service` (str, ex : `"chatbot-bi"`, `"toupac-crm-sage"`).
- `is_active` (bool).
- `granted_at`, `revoked_at`.
- Créé par superadmin TOUPAC quand un tenant s'abonne à un service
  plateforme. Le tenant lui-même ne crée pas ces entrées.

### Flow d'appel du chatbot

1. Le chatbot reçoit **UNE** `PlatformCredential` au démarrage du projet
   (émise par superadmin TOUPAC, transmise via canal sécurisé, stockée
   dans son secret manager AWS).
2. À chaque conversation utilisateur, le chatbot sait sur quel tenant
   elle porte (déterminé par sa propre session utilisateur — l'utilisateur
   du chatbot est identifié comme employé de Sahel Express).
3. Le chatbot appelle l'API TOUPAC avec deux headers :
   - `X-API-Key: tpc_platform_XXXX.YYYYYY...`
   - `X-Tenant-ID: sahel-express`
4. Côté serveur, un nouveau backend `PlatformApiKeyAuthentication` :
   - Résout la `PlatformCredential` depuis `X-API-Key`.
   - Vérifie que l'IP source ∈ `allowed_ips`.
   - Vérifie que la clé n'est pas expirée / révoquée.
   - Lit `X-Tenant-ID` et résout le `Tenant`.
   - Vérifie qu'un `TenantSubscription(tenant=X, platform_service=Y,
     is_active=True)` existe.
   - Attache `request.tenant` et `request.platform_credential`.
5. Le reste du stack fonctionne comme avant : `TenantManager` filtre les
   querysets par `request.tenant`, `HasApiScope` (variante plateforme)
   vérifie les scopes.

### Nouveau tenant s'abonne au chatbot ?

Zéro action côté équipe chatbot. Zéro déploiement, zéro secret à
transmettre, zéro configuration.

Le superadmin TOUPAC :

1. Crée le tenant (déclenche le signal `post_save` qui provisionne le
   service account, cf. doctrine iam actuelle).
2. Va dans `/admin/iam/tenantsubscription/` et crée l'entrée
   `(tenant=nouveau-tenant, platform_service="chatbot-bi",
   is_active=True)`.

Dès la prochaine requête du chatbot avec `X-Tenant-ID: nouveau-tenant`,
l'API répond correctement. Onboarding en 2 clics.

### Endpoints "globaux" — refus du `X-Tenant-ID`

Certains endpoints doivent être appelables sans contexte tenant :

- `GET /platform/tenants/` — liste des tenants abonnés au service (le
  chatbot en a besoin pour savoir sur quel tenant router une conversation
  d'utilisateur non encore identifié).
- `GET /platform/subscriptions/` — statut de sa propre abonnement.
- `GET /platform/health/` — check de santé de la clé.

Ces endpoints refusent explicitement `X-Tenant-ID` (400 si présent), et
sont marqués `platform:global:*` dans les scopes. Toute la logique est
dans une permission dédiée `IsPlatformGlobalEndpoint` qui interagit avec
le middleware d'auth.

Les endpoints tenant-scopés (`/api/v1/voyage/routes/`, etc.) **exigent**
`X-Tenant-ID` quand appelés avec une `PlatformCredential` (400 sinon).

## Portée pour le chatbot en V1 : lecture uniquement

Décision prise : le chatbot **n'émet pas de notifications** en V1.

Raison. Le chatbot est un traducteur langage naturel → API. Sa nature
première est la lecture (« Où est mon colis ? » → GET). L'émission de
notification a des effets réels (vibration téléphone chauffeur, SMS
payant, alerte centre) qui demandent un contrôle strict. Un utilisateur
malicieux qui manipulerait le chatbot pour déclencher un broadcast push
à tous les chauffeurs d'un tenant serait catastrophique — TOUPAC ne
maîtrise ni le prompt système du chatbot, ni les guardrails de l'équipe
partenaire.

Conséquence pratique :

- Scopes accordés au chatbot : `platform:voyage:read`, `platform:colis:read`,
  `platform:tracking:read`, `platform:billing:read`,
  `platform:notifications:read` (lire les notifs déjà émises pour un
  utilisateur donné), `platform:global:read` (liste des tenants abonnés).
- **Pas** de `platform:*:write`.
- **Pas** de `platform:notifications:emit`.
- Toupac CRM (adaptateur Sage/Odoo) peut avoir des scopes en écriture
  plus tard — c'est une décision par service plateforme, pas globale.

Si un jour on veut que le chatbot puisse répondre dans une conversation
avec un lien / un rappel, ce sera un **mécanisme dédié séparé** (API
`POST /chatbot-conversations/{id}/reply/` contrainte au canal chat), pas
via le système de notifications général.

## Mitigations sécurité

Une `PlatformCredential` compromise donne accès aux données de tous les
tenants abonnés au service — surface d'attaque significative. Cinq
mitigations câblées dans le ticket d'implémentation :

**1. Rotation forcée par expiration**

`expires_at` obligatoire à la création, par défaut à +90 jours.
L'émission d'une nouvelle clé peut se faire avant l'expiration de
l'ancienne. Fenêtre de rotation : les deux clés valides simultanément
pendant N jours (paramétrable, défaut 7). Le chatbot bascule sans
coupure.

**2. Allowlist IP (CIDR)**

Chaque `PlatformCredential` porte une liste d'IP autorisées. En pratique
pour le chatbot AWS : l'IP publique fixe (Elastic IP) ou le range CIDR
d'un NAT Gateway. Requête depuis autre IP → 403 immédiat, journalisation
d'incident.

**3. Alertes d'usage anormal**

Job Celery quotidien qui compare le trafic par tenant, par heure, par
endpoint à une baseline glissante (moyenne des 7 derniers jours ±
écart-type). Écart > 3σ ou pic > 5× la moyenne → email d'alerte à l'admin
TOUPAC avec détail (tenant concerné, endpoint, volume, IP source).
Détection rapide de : chatbot compromis qui exfiltre, chatbot qui a un
bug de boucle infinie, chatbot qui commence à taper des tenants non
abonnés.

**4. Log d'audit détaillé**

Nouveau modèle `PlatformAuditLog(credential, tenant_context, endpoint,
method, ip, user_agent, status_code, response_size, created_at)` — une
entrée par requête. Volumétrie estimée : ~1000 requêtes/jour/tenant à
maturité, gérable. Rotation ou archivage après 90 jours.

**5. Scope minimal explicite, pas de `platform:*`**

Contrairement à `admin:*` qui existe côté `ApiCredential` (usage TOUPAC
interne), il n'y aura **pas** de super-scope `platform:*`. Chaque
`PlatformCredential` est émise avec un ensemble explicite de scopes.
Cohérent avec la doctrine « pas de super-scope pour partenaire externe »
posée pour les tenants (`admin:*` refusé pour non-superadmin).

## Pourquoi pas OAuth 2.0 client credentials

L'alternative naturelle est OAuth 2.0 flow *client credentials* (RFC 6749),
standard entreprise pour l'auth de services. Analyse comparative.

**Ce qu'OAuth 2.0 CC apporte vraiment** :

- Token d'accès court (typiquement 1h), obtenu contre le secret client
  via un endpoint `/oauth/token/`. Une requête interceptée expose un
  token qui expire vite, pas un secret indéfini.
- Rotation de secret plus douce (protocole standard).
- Interopérabilité (SDK OAuth pour tous les langages).

**Ce qu'OAuth 2.0 CC ne résout pas mieux** :

- La compromission du secret client donne quand même accès à tous les
  tenants abonnés — c'est le risque cardinal, il est identique.
- Le multi-tenant (`X-Tenant-ID` header ou `audience` claim JWT) — même
  design nécessaire.
- La révocation immédiate — nécessite une denylist Redis dans les deux
  cas.

**Coûts spécifiques d'OAuth 2.0 CC** :

- 2 modèles au lieu de 1 (`OAuthClient` + `OAuthAccessToken`).
- Nouvel endpoint `/oauth/token/` (validation, génération JWT, denylist).
- L'équipe chatbot doit implémenter la logique de refresh (30 lignes,
  simples mais un bug potentiel).
- Nouvel endpoint `/oauth/revoke/`.
- Backend d'auth DRF différent.

Estimation +1 jour vs `PlatformCredential` brute.

**Décision : Option A (`PlatformCredential` + `X-Tenant-ID`) pour V1.**

Raisonnement :

1. Le vrai risque (compromission secret partagé) est identique. Les
   mitigations (rotation, allowlist IP, alertes) sont identiques.
2. Le chatbot est développé par une équipe externe qu'on ne contrôle
   pas. Un protocole simple = moins de bugs d'intégration chez eux.
3. À N=1 client plateforme aujourd'hui (le chatbot), le standard OAuth
   est du sur-engineering. Il prend son sens à N=3+ clients avec des
   politiques de rotation différentes.
4. Migration future vers OAuth 2.0 CC = petit ticket (~2 jours) si le
   besoin apparaît. L'inverse (partir OAuth, revenir clé brute) est
   plus coûteux — on a construit du code qu'on jette.

Ligne de bascule : dès qu'on a 3+ services plateforme distincts, ou
qu'un audit sécurité l'exige, on ouvre le ticket de migration OAuth 2.0 CC.

## Impact sur les tickets en cours (Ticket B notifs)

Minimal. Le Ticket B (`NotificationService.emit()`) est appelé
**uniquement par le code métier interne**, pas par une clé API externe.
Pas de scope `platform:notifications:write` à câbler, pas de validation
« cet appelant a-t-il le droit d'émettre au nom de ce tenant ? ».

Le scope `platform:notifications:read` (lecture du centre d'alertes pour
un utilisateur donné) est câblable au Ticket D (endpoints in-app) via
une variante de permission qui accepte les deux backends d'auth
(`ApiKeyAuthentication` et `PlatformApiKeyAuthentication`). C'est du
travail de connectique, pas de conception.

Conclusion : ce ticket peut se faire **avant** ou **après** le Ticket B
selon les priorités produit, il ne bloque ni ne dépend de la refonte
notifs.

## Contrat pour l'équipe chatbot externe

À partager en même temps que la clé de test.

**Ce que nous vous fournissons** :

- Une `PlatformCredential` de test pour l'environnement staging (préfixe
  `tpc_platform_stg_`).
- Une `PlatformCredential` de production après validation de l'intégration
  et audit d'IP source.
- La liste des scopes accordés (revue périodique semestrielle).
- Un endpoint `GET /platform/tenants/` pour découvrir dynamiquement les
  tenants abonnés au service.
- Le portail développeur `/developers/platform/` (déclinaison du portail
  actuel, adaptée aux appels plateforme).
- Un canal Slack ou email dédié pour alertes sécurité et rotation.

**Ce que nous attendons de vous** :

- Stockage de la clé dans un secret manager (AWS Secrets Manager, Google
  Secret Manager, HashiCorp Vault — pas d'env-var, pas de commit git).
- IP source stable (Elastic IP AWS ou équivalent), communiquée à TOUPAC
  pour l'allowlist.
- Rotation coopérative : quand nous vous envoyons la nouvelle clé, vous
  déployez la bascule dans les 7 jours.
- Logging côté chatbot des appels API émis (au moins `endpoint`, `tenant`,
  `status_code`, `latency`) pour débug conjoint en cas d'incident.
- Aucune tentative d'accéder à un endpoint non listé dans le portail
  développeur — nous détectons et alertons.
- Notification immédiate en cas de compromission suspectée du secret.

**Ce que nous NE fournirons PAS** :

- Une clé par tenant (l'onboarding d'un nouveau tenant chez vous doit
  être zéro-effort).
- Un scope `platform:*` équivalent à un accès total (les scopes sont
  minimaux et explicites).
- Un scope d'émission de notification en V1 (le chatbot lit, il n'émet
  pas). À rediscuter en V2 avec un mécanisme dédié si le besoin apparaît.

## Prochaines étapes

Cette note est une proposition. Actions attendues avant implémentation :

1. **Validation par le lead TOUPAC** — la modélisation à deux types
   (tenant vs plateforme) et le choix Option A vs OAuth 2.0 CC.
2. **Confrontation avec l'équipe chatbot** — le contrat ci-dessus est-il
   acceptable de leur côté (IP fixe, rotation coopérative, secret
   manager) ? Ont-ils un besoin d'émission de notifications que je
   sous-estime ?
3. **Décision de séquencement** — ticket d'implémentation avant ou après
   le Ticket B refonte notifs ? Recommandation : **avant**, parce que la
   question est mûre maintenant et parce qu'elle peut légèrement toucher
   au design des permissions du Ticket D (endpoints in-app).
4. **Rédaction du ticket d'implémentation** — Opus 4.7, ~1.5-2 jours,
   ~25-30 tests attendus.
