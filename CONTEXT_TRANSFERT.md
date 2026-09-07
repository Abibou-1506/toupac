# TOUPAC — Transfert de contexte

_Généré le 2 sept 2026 après une longue session de sprint applicatif._
_Mis à jour le 5 sept 2026 après la série de tickets iam-admin._
_Mis à jour le 6 sept 2026 après les Tickets notifications-warmup / A / A' — 191 tests verts._
_Mis à jour le 7 sept 2026 après le chantier CLIENT global (série iam-platform-credentials + USR-1 à USR-4) — 476 tests verts, architecture marketplace B2B2C posée._
_À coller en premier message du nouveau chat Claude Opus 4.7._

## Projet et rôle

TOUPAC = TMS SaaS pour compagnies de transport ouest-africaines (UEMOA + CEDEAO).
Développement sur-mesure Django/DRF/PG-PostGIS. Le client est une compagnie
malienne (Bamako, corridors Bamako-Ségou-Bla, Bamako-Kayes-Dakar, Bamako-Bouaké-Abidjan).

Je suis **freelance en période d'essai (2 mois)**. Rôle **architecte technique
principal** côté backend. Une équipe mobile RN travaille sur Toupac Control
(app contrôleur) en parallèle, une équipe partenaire externe attaque bientôt un
chatbot IA (Toupac BI) qui consommera notre API — **le chantier CLIENT global
du 7 sept a posé les fondations de son intégration** (PlatformCredential +
acting user + endpoints `/customer/my-*`).

Le projet local est à `C:\Dev\toupac_django\toupac` (accessible via
filesystem MCP). Trois fichiers de vérité à la racine :

- **`CONTEXT_TRANSFERT.md`** (ce fichier) — état du projet à jour
- **`DECISIONS.md`** — registre des patterns/anti-patterns validés au fil des tickets (42+ entrées, groupé en 10 domaines)
- **`DETTES.md`** — dette identifiée + section « Fonctionnel — À venir » pour les gros chantiers cadrés

Une note de design vit à part :
- **`docs/design/platform-credentials.md`** — architecture PlatformCredential (Type 1 tenant vs Type 2 plateforme), OAuth 2.0 CC écarté, mitigations sécu.

## Stack et décisions d'architecture figées

- **Django 5 + DRF + GeoDjango**
- **PostgreSQL 16 + PostGIS 3.4**
- **Redis 7** (cache, throttling, denylist tokens, storage OTP, Celery broker)
- **Celery 5** (jobs asynchrones, beat)
- **Channels 4** installé pour WebSocket (pas encore utilisé)
- **django-unfold** pour l'admin (sidebar déclarée explicitement dans `UNFOLD["SIDEBAR"]["navigation"]`, pas auto-générée)
- **drf-spectacular** pour OpenAPI/Swagger
- **rest_framework_simplejwt** pour JWT (customisé avec denylist)
- **django-guardian** installé — `AnonymousUser` provisionné avec rôle `SERVICE_ACCOUNT` via `iam/guardian.py` (USR-1)
- **Docker Compose** dev (4 conteneurs) + prod (7 services + Caddy)
- **cryptography** pour RS256 des QR billets

Monolithe modulaire (pas microservices). **Architecture marketplace B2B2C** :
TOUPAC (plateforme) × compagnies (tenants) × passagers/expéditeurs (CLIENT
global). Multi-tenant strict pour les rôles opérationnels des compagnies,
tenantless pour le rôle CLIENT.

## Modules Django et responsabilités

10 modules, ~50 modèles au total :

| Module | Responsabilité |
|---|---|
| `core` | Mixins de base (TenantModel, UUIDv7, SoftDelete), TenantMiddleware (accepte `X-Tenant-ID` en slug OU UUID depuis USR-2), TenantManager, TenantAdminMixin. `SoftDeleteMixin` n'a pas de manager filtrant — chaque queryset pose `deleted_at__isnull=True` explicitement. |
| `iam` | Tenant, User (custom AbstractBaseUser, 8 rôles + CLIENT tenantless depuis USR-1), `get_or_create_service_account()`, `get_or_create_platform_bot()`, `get_or_create_client()`. **Deux types d'intégrations API** : `ApiCredential` (par tenant, USR-0 iam-admin) + `PlatformCredential` (par service plateforme, série iam-platform + USR-4). `PlatformAuditLog` avec champ `acting_user`. Modules OTP (`otp.py`, `otp_views.py`), endpoints CLIENT (`customer_views.py`). |
| `fleet` | VehicleType, Vehicle, Driver, VehicleDocument, Fleet, FleetVehicle |
| `geo` | Place (tenant nullable pour places publiques), Zone |
| `workflow` | WorkflowDefinition, State, Transition, Hook (configurable en DB) |
| `voyage` | Route, RouteStop, Schedule, SeatMap, Trip, TripStop, **Passenger + Passenger.customer_user (FK vers User CLIENT global, USR-3)**, Reservation, Controller, ControlSession, ControlEvent (batch offline), Anomaly, Incident, CashEntry, PassengerAccessLog, LuggagePolicy |
| `colis` | Order (`customer` FK réutilisée vers User CLIENT global depuis USR-3), Parcel, DeliveryTask, ProofOfDelivery |
| `billing` | PriceList, PriceRule, Invoice (`customer_id` UUID générique + `customer_type="client_user"` documenté en USR-3), InvoiceLine, Payment (Intouch mobile money sandbox) |
| `tracking` | Position (pas TenantModel, BigAutoField pour volumétrie), Geofence, GeofenceEvent, TrackingLink |
| `notifications` | **Refonte en cours selon charte TOUPAC ONE.** Tickets warmup + A + A' fermés. Modèles : `NotificationTemplate`, `Notification` (item du centre d'alertes), `NotificationLog` (delivery attempts, `tenant` nullable depuis USR-2 pour OTP CLIENT global). Catalog déclaratif 37 events (`catalog.py`), resolvers (`resolvers/`), catégories de préférences (`preferences.py`). `NotificationService.emit()` refondu au Ticket B (à venir). |
| `developers` | **Portail split (USR-4)** : `/developers/` (mode tenant ApiCredential) + `/partners/developers/` (mode plateforme PlatformCredential + acting user). Renvois croisés en tête de chaque page. |

## Périmètre produit confirmé par le lead

Suite "TOUPAC ONE" = 7 apps, mais **notre équipe backend produit uniquement** :
- **Toupac 360** (backoffice, Django admin aujourd'hui, console React V1.5)
- **Toupac Control** (app mobile contrôleur, dev RN en cours)
- **Toupac Driver** (app mobile chauffeur, à venir)
- **App client fusionnée Cargo + Go** (voyages + colis, à venir — auth OTP CLIENT prête, endpoints `/customer/my-*` prêts)

Nous **préparons l'API** consommée par :
- **Toupac CRM** = intégrations ERP tierces (Sage, Odoo) — Type 2 plateforme
- **Toupac BI** = chatbot IA développé par équipe externe qui a gagné le marché — Type 2 plateforme, **fondations posées au chantier CLIENT global**

## Décisions produit tranchées par le lead (rendez-vous du 2 sept 2026)

1. **SMS et WhatsApp = strictement OTP-only**. Tous les autres canaux → Push + In-app + Email selon la charte notifications TOUPAC ONE.
2. **7 apps = vision cible, pas V1**. On construit un backend unifié + 4 fronts (voir périmètre ci-dessus).
3. **Tramingo = intégration (pas remplacement par Traccar)**. Doc API v1.7 en main, polling REST classique, OAuth 2.0 password grant, événements pré-calculés dispos (excès vitesse, sortie zone, etc.).
4. **Coordination Dispatcher↔Chauffeur = notifications unidirectionnelles avec accusés de lecture** (pas de messagerie bidirectionnelle en V1). Traçabilité préservée. Porte ouverte architecture pour rabattre vers option messagerie plus tard.

## Décisions doctrine IAM tranchées (3-5 sept 2026)

Clarifications produites en même temps que les 3 tickets iam-admin.

1. **Scope `admin:*` = TOUPAC interne uniquement**. Réservé aux intégrations
   internes TOUPAC (outillage superadmin, adaptateurs Toupac CRM maintenus par
   TOUPAC). Aucun tenant client n'a de cas d'usage légitime. **Blocage dur**
   dans `ApiCredentialCreateForm.clean_scopes()` pour tout émetteur
   non-superadmin. Fail-closed quand `_request` est None. Docstring `iam/scopes.py`
   et portail `/developers/` alignés.

2. **Service account par tenant**. Chaque tenant est doté automatiquement
   (signal `post_save(Tenant)`) d'un compte technique : email
   `api-bot@<tenant.slug>.internal`, rôle `User.Role.SERVICE_ACCOUNT`,
   `set_unusable_password()`. Toutes les clés API du tenant pointent vers ce
   compte. Auto-guérison si supprimé.

3. **Séquencement gros chantiers IAM**. Refonte notifications d'abord.
   Self-service user management pour admins de compagnie après (avec
   durcissement `UserAdmin` anti-escalade). Tracé en `DETTES.md`.

## Décisions doctrine architecture marketplace B2B2C tranchées (6-7 sept 2026)

**Le chantier le plus structurant du projet**. Produit en 5 tickets (iam-platform-credentials + USR-1 à USR-4). Redéfinit la nature multi-tenant de TOUPAC.

1. **TOUPAC est un marketplace B2B2C, pas juste un SaaS multi-tenant.**
   - Le "B" central = TOUPAC.
   - Le "B" intermédiaire = les compagnies (tenants — Sahel Express, Dem Dikk).
   - Le "C" = les passagers/expéditeurs/destinataires — **clients directs de TOUPAC**, pas des tenants.
   - Conséquence structurelle : le rôle CLIENT bascule sur `tenant=None`. Tous les autres rôles opérationnels (ADMIN, DISPATCHER, AGENT, DRIVER, CONTROLLER) restent tenant-scopés.

2. **Deux types d'intégrations API distinctes, deux modèles séparés.**
   - **Type 1 tenant** : `ApiCredential`. Une clé par tenant, émise par l'admin de la compagnie pour ses propres intégrations privées (ERP maison, CRM custom). Modèle en place depuis iam-admin.
   - **Type 2 plateforme** : `PlatformCredential`. Une clé par service central TOUPAC (chatbot Toupac BI, futures apps mobiles officielles, adaptateur Toupac CRM). Émise par superadmin TOUPAC. Le tenant cible est indiqué par header `X-Tenant-ID` (slug) sur chaque requête. Pas de FK tenant sur la clé.

3. **Le chatbot Toupac BI est disponible pour tous les tenants dès leur création.**
   - Retrait du concept `TenantSubscription` (sur-engineering écarté en USR-4).
   - Endpoint `/api/v1/platform/tenants/` liste tous les tenants ACTIVE+TRIAL, sans filtre subscription.
   - Un nouveau tenant créé → immédiatement accessible au chatbot sans action superadmin.

4. **Acting user : `X-Acting-User-Email` (ou `X-Acting-User-Phone`) pour agir au nom d'un CLIENT via clé plateforme.**
   - Résolution via `User.get_or_create_client()` — le CLIENT est créé silencieusement s'il n'existe pas.
   - `request.user` devient ce CLIENT pour toute la vie de la requête (pas le porteur du secret).
   - Le platform-bot ne sert plus qu'aux endpoints globaux (`/platform/tenants/`, `/platform/health/`).
   - Priorité `email > phone` (cohérente avec OTP USR-2).
   - Cross-app : Fatou parle au chatbot WhatsApp avec son phone, télécharge l'app mobile TOUPAC plus tard, se connecte par OTP email — **elle retrouve son historique** grâce à `get_or_create_client` idempotent.

5. **Auth CLIENT OTP-only** (pas de mot de passe).
   - `POST /api/v1/auth/otp/request/` → OTP envoyé par email OU SMS/WhatsApp.
   - `POST /api/v1/auth/otp/verify/` → JWT émis.
   - Storage Redis, hash SHA256 du code (jamais en clair, même en cache volatil), TTL 5 min, max 3 tentatives.
   - **Staff continue en email + password** classique.
   - **`staff.email` obligatoire** (USR-2) : contrainte DB `user_staff_has_email` + validation `clean()`.

6. **Trois rôles CLIENT distincts, jamais fusionnés.**
   - **Voyageur** = `Passenger.customer_user` (nouveau FK optionnel USR-3).
   - **Commanditaire colis** = `Order.customer` (FK existante, sémantique clarifiée).
   - **Payeur** = `Invoice.customer_id` + `customer_type="client_user"`.
   - Fatou passagère d'un billet payé par son mari : elle voit son billet dans `my-reservations`, il voit le paiement dans `my-payments`. Aucun croisement.

7. **Endpoints CLIENT-scoped cross-tenant** (`/api/v1/customer/*`) :
   - `/customer/me/`, `/customer/companies/`, `/customer/my-reservations/`, `/customer/my-orders/`, `/customer/my-payments/`.
   - Bypass `TenantManager` via `all_objects.filter(...)` — `request.tenant` est None pour un CLIENT.
   - Chaque item retourne `tenant_slug` + `tenant_name` (le CLIENT doit savoir chez qui il a acheté).
   - Serializers **liste blanche** stricte : jamais de `created_by`, `qr_code_jwt`, `metadata`, `provider_response`.
   - Filtres optionnels `?tenant=<slug>` pour affiner.
   - Ces endpoints acceptent **JWT direct** (auth CLIENT app mobile) **ET** `PlatformApiKeyAuthentication + X-Acting-User-Email` (chatbot). Permission composée : scope `platform:customer:read` requis dans le second cas.

8. **Écriture métier ouverte via `platform:*:write`.** Le chatbot peut réserver un voyage, envoyer un colis, initier un paiement au nom d'un CLIENT résolu (USR-4).
   - `platform:voyage:write`, `platform:colis:write`, `platform:billing:write`.
   - **Deux conditions cumulatives** : scope write ET acting user présent. Une écriture sans acting user est refusée (attribuer une réservation au platform-bot produirait un enregistrement sans titulaire).
   - **Pas** de scope `platform:notifications:emit` : émettre une notification reste un side-effect direct à contrôle strict, réservé au code métier interne.

9. **Double throttle sur endpoints CLIENT-scoped en mode PlatformCredential.**
   - `PlatformKeyRateThrottle` (1000/h par clé) — protège la plateforme.
   - `ActingCustomerRateThrottle` (200/h par CLIENT résolu) — protège l'individu.
   - DRF applique tous les throttles, le plus contraignant l'emporte.

10. **Trace audit fine "qui, pour qui, où".**
    - `PlatformAuditLog(credential, acting_user, tenant_context)` — trois champs pour trois questions.
    - `on_delete=SET_NULL` sur acting_user : effacer un compte ne doit pas effacer la trace des accès dont il a fait l'objet.
    - Admin superadmin filtre et cherche par acting_user.

11. **`PlatformCredential.expires_at` optionnel, `allowed_ips` optionnelle.**
    - Rotation forcée à 90 jours écartée (retirer une garantie sécu = arbitrage documenté, pas relâchement — voir DECISIONS.md).
    - Allowlist IP fortement recommandée mais vide autorisée (chatbot serverless).
    - Vrais garde-fous : révocation immédiate + audit log + rate limiting.

12. **Portail développeur split par public, pas par sujet.**
    - `/developers/` — mode tenant. Public : intégrateurs d'une compagnie.
    - `/partners/developers/` — mode plateforme. Public : équipes partenaires externes (chatbot, apps mobiles officielles).
    - Renvois croisés d'une phrase en tête de chaque page.

13. **Pas de fusion automatique de comptes.**
    - Un CLIENT « email seul » qui tente OTP par un phone jamais associé crée un **deuxième** CLIENT. Fusionner exige une preuve de propriété qu'un helper `get_or_create` ne peut pas établir.
    - Feature future `POST /customer/add-contact/` (auth CLIENT + OTP de confirmation sur le nouveau canal) tracée en dette.

## Décisions doctrine notifications tranchées (5-6 sept 2026)

Clarifications produites au fil de la refonte (Tickets warmup, A, A').

1. **Convention `notif.{domaine}.{evenement}.{version}`** — verrouillée par la charte TOUPAC ONE. Codes canoniques choisis : `notif.order.*` (pas `command.*`), `notif.platform.system_incident.v1` (pas `si.*`).

2. **Push + In-app OBLIGATOIRES** sur tous les événements non-OTP. Email selon cas. SMS/WhatsApp uniquement OTP. 32/37 events en Push, 18/37 en Email, 3/37 en SMS, 3/37 en WhatsApp.

3. **EventCatalog en code = source unique de vérité** (`notifications/catalog.py`). Validation à l'import. Évolution d'un event = nouvelle version (`.v1` → `.v2`).

4. **Service explicite `NotificationService.emit()`, pas signals Django.**

5. **Une `Notification` = un `recipient_user`.** Broadcast rôle génère N Notifications individuelles.

6. **`variables_schema` en format Python natif** (pas JSON Schema, pas Pydantic). Attention : `isinstance(x, int)` accepte `bool` — exclure explicitement.

7. **Préférences user via `User.notification_preferences` (JSONField).** 3 catégories NEVER_OPT_OUT : `otp`, `security`, `critical_ops`.

8. **Confidentialité (N-05) asymétrique par canal** : push masque, in-app et email portent le payload complet. À intégrer explicitement au Ticket B.

## État du sprint applicatif au 7 sept 2026

**Ce qui est fait (base historique)** :
- Feature `session_id` batch offline (contrat verrouillé avec dev RN)
- QR billets RS256 end-to-end + endpoint public `/qr-public-key/`
- Tests critiques : auth (JWT + denylist), multi-tenant isolation API, workflow transitions, paiement Intouch mocké
- Seed démo réaliste 2 tenants (Sahel Express, Dem Dikk) — commande `seed_demo` idempotente, appelle `seed_notification_templates`
- Access token denylist Redis
- **Fondations API publique** : 15 scopes tenant + 10 scopes plateforme

**Livré dans la série iam-admin (3-5 sept 2026)** :
- Génération de clé API depuis Django Admin (multi-select scopes, révélation one-shot TTL 5 min, AuditLog sans secret, test end-to-end).
- Démo-ready (4 permissions `*_apicredential` ajoutées au groupe staff, refus `admin:*` non-superadmin).
- Service accounts par tenant.

**Livré dans la série notifications (5-6 sept 2026, 191 tests)** :
- Warm-up : retour None silencieux corrigé, canal IN_APP ajouté.
- Ticket A : Modèles enrichis, EventCatalog (37 events), Resolvers, `User.notification_preferences`.
- Ticket A' : Correctifs codes canoniques (order, platform, INC-02).

**Livré dans le chantier CLIENT global (6-7 sept 2026, 476 tests, +208 vs pré-chantier)** :

- **iam-platform-credentials (6 sept)** — Fondations Type 2 plateforme.
  - `PlatformCredential`, `TenantSubscription` (retiré en USR-4), `PlatformAuditLog`, scopes `platform:*`, backend d'auth, allowlist IP CIDR (stdlib ipaddress), rate throttle, admin superadmin, endpoints `/platform/tenants/`, `/platform/health/`, portail dev enrichi. 268 → 380 tests.
  - Bugs préexistants découverts : `/auth/me/` échappe aux scopes (dette tracée xfail strict), collision sémantique `X-Tenant-ID` (traitée en USR-2).

- **USR-1 (6 sept)** — Fondation CLIENT tenantless (317 tests).
  - `User.tenant` nullable pour CLIENT. Contraintes DB : `user_tenant_matches_role`, `user_client_phone_unique`, `user_client_has_contact`, `unique=True + null=True` sur email (pas UniqueConstraint partielle car incompatible `auth.W004` sur USERNAME_FIELD).
  - `User.get_or_create_client()` idempotent, refuse de voler un identifiant.
  - Migration `iam/guardian.py` pour AnonymousUser → SERVICE_ACCOUNT (aurait cassé pytest sur base neuve sinon).
  - 4 clients de démo seedés couvrant email seul / phone seul / les deux.

- **USR-2 (6 sept)** — Auth OTP CLIENT + middleware 3 régimes (380 tests, +63).
  - `POST /auth/otp/request/` + `/verify/`. Storage Redis TTL 5 min, hash SHA256, secrets.compare_digest, échéance absolue dans payload (pas via TTL Redis inaccessible).
  - `TenantMiddleware._resolve_from_header` accepte slug ET UUID.
  - Endpoints `/customer/me/`, `/customer/companies/`.
  - `staff.email` obligatoire (CheckConstraint + clean()).
  - Correctif blocage : `NotificationLog.tenant` devient nullable (migration `notifications/0006`) — sinon OTP CLIENT global impossible.
  - Templates `notif.auth.otp_signin.v1` seedés (SMS, WhatsApp, Email, In-App).

- **USR-3 (7 sept)** — Modèles métier + endpoints CLIENT (404 tests, +24).
  - `Passenger.customer_user` (FK optionnelle vers User CLIENT).
  - `Order.customer` réutilisée, sémantique clarifiée. Migration data nettoyage.
  - `Invoice.customer_type = "client_user"` documenté (constantes exposées).
  - Endpoints `/customer/my-reservations/`, `/my-orders/`, `/my-payments/` avec union `.distinct()`.
  - `all_objects = models.Manager()` ajouté aux modèles concernés.
  - Serializers stricts liste blanche, `tenant_slug` par item.
  - 2 clients seedés (`client-demo-1@toupac.demo`, `client-demo-2@toupac.demo`) avec réservations et orders réparties sur les 2 tenants.

- **USR-4 (7 sept)** — Correctif chatbot + acting user + portail split (476 tests, +72).
  - Suppression `TenantSubscription`.
  - `PlatformCredential.expires_at` nullable, `allowed_ips` liste vide autorisée partout.
  - 4 nouveaux scopes plateforme (write × 3 + customer:read).
  - Header `X-Acting-User-Email` / `X-Acting-User-Phone` résolu dans `PlatformApiKeyAuthentication`.
  - `PlatformAuditLog.acting_user` FK nullable + admin filtre.
  - Double throttle sur `/customer/*` en mode plateforme (`ActingCustomerRateThrottle` 200/h par CLIENT).
  - Permission composée `IsAuthenticatedCustomer` (JWT direct OU plateforme + scope).
  - Portail split : `/developers/` + `/partners/developers/`.
  - Bug critique corrigé : sentinelle `_WRITE_REFUSED` remplacée par dérivation naturelle.
  - Doc réécrite (« déplacée pas refaite » cédé face à l'obligation de vérité).

**Ce qui reste (Phase 2 immédiate)** :
- **Ticket B — NotificationService v2 (Opus 4.7, ~2 jours)** — Refonte du service selon charte. `emit(event_code, actor, context)` remplace `send_notification()`. Validation contexte, résolution destinataires, application préférences (N-02), idempotence (N-06) via Redis, création Notification + NotificationLog, enqueue Celery per delivery. Retry différencié par canal (N-09). Confidentialité asymétrique par canal. Fail-log symétrique (template absent, template cassé, resolver absent, resolver qui lève).
- **Tickets C/D/E1/E2/F** — Sonnet 4.5 chacun, ~1 jour. C: providers réels (FakePushProvider). D: endpoints in-app centre d'alertes (côté CLIENT, en réutilisant permission composée USR-4). E1/E2: câblage métier (~29 resolvers). F: seed des 37 templates.

**Micro-tickets courts prêts à insérer entre 2 gros tickets** :
- Route↔RouteStop cohérence (~30 min) — validation `Route.clean()`.
- `/qr-public-key/` warning au lieu de crash (~20 min).
- `/auth/me/` scope check harmonisé (~1h) — dette USR-2 avec xfail strict.

**Phases suivantes** (dans l'ordre) :
- Phase 2 (suite) : intégration Tramingo (polling REST, mapping IMEI→Vehicle, événements pré-calculés → notifs GPS-01/02), intégration FCM/APNs (canal Push réel remplace FakePushProvider), import Excel client, enrichissements modèle, ré-alignement seed (marques YUTONG, corridors Mali).
- Phase 3 : self-service user management pour admins de compagnie, endpoints d'écriture CLIENT via app mobile directe (`POST /customer/reservations/`, `POST /customer/orders/`), feature `add-contact-to-existing-account`, `Order.recipient_user` (asymétrie destinataire ≠ commanditaire).
- Phase 4 : webhooks sortants HMAC (Surface B ERP), Metabase branché reporting.
- Phase 5 : MFA TOTP admin, Import CSV commandes, micro-dettes restantes.

## Conventions de code établies

**Tests** :
- pytest + pytest-django avec `conftest.py` racine ET `iam/tests/conftest.py` local (fixtures partagées : `tenant_a`, `tenant_b`, `user_admin_a`, `user_admin_b`, `user_dispatcher_a`, `user_controller_a`, `authenticated_client`, `client_fatou`, `client_aicha`, `superadmin`, `_isolated_throttle_cache` autouse).
- Un package `tests/` par module.
- Utiliser **de vrais JWT** pour tester l'auth (pas `force_authenticate`).
- Tests admin : `Client()` + `client.force_login(user)`, PAS `APIClient`.
- Assertions sur le **contenu**, pas juste le status code.
- Assertions HTML sur UUID/attributs, pas sur labels affichés.
- **Test end-to-end obligatoire** pour toute émission de credential/token.
- **Data migration non triviale = test dédié** via `importlib.import_module` + `apps.get_model` (exceptions documentées dans DECISIONS.md).
- **Tests data-driven sur invariants** — itérer sur `all_events()`, `all_scopes()`, etc.
- **Assertions négatives sur doc publique** : `assert "rotation" not in html` pour traquer les affirmations obsolètes.
- **Compter les queries d'un serializer** (`assertNumQueries`) sur les endpoints listant avec serializer imbriqué, pas de seuil absolu mais canari.
- **Tester le double throttle** en abaissant les seuils drastiquement (2/h, 1/h) — la mécanique est prouvée, pas la valeur.

**Ruff** :
- Config dans `pyproject.toml` avec `select = ["E", "F", "W", "I", "B", "C4", "UP", "RUF"]`.
- `RUF012` désactivé, `EXE002` non sélectionné, `E402` ignoré sur `config/settings/*.py`.
- `UP042` actif — `StrEnum` obligatoire.

**Répartition des 3 fichiers de vérité** :
- **DETTES.md** : dette identifiée à traiter.
- **DECISIONS.md** : patterns/anti-patterns validés (42+ entrées, 10 domaines).
- **CONTEXT_TRANSFERT.md** (ce fichier) : état du projet, doctrine produit, décisions structurantes, plan de séquencement. Pointe vers DECISIONS.md pour le détail des patterns.

**Commits** :
- Convention `feat(scope): ...`, `fix(scope): ...`, `chore(scope): ...`, `test(scope): ...`, `docs: ...`, `refactor(scope): ...`.
- Body avec contexte + résultats chiffrés + refs vers tickets/dettes.
- 1 commit par ticket, atomique.

## Fichiers-clés à connaître dans le repo

**Racine** :
- `CONTEXT_TRANSFERT.md`, `DECISIONS.md`, `DETTES.md` — les 3 fichiers de vérité.
- `conftest.py` — fixtures partagées.
- `docs/design/platform-credentials.md` — architecture Type 1 vs Type 2, OAuth 2.0 CC écarté.

**Config** :
- `config/settings/base.py` — REST_FRAMEWORK config (auth chain, throttles, `acting_customer: 200/hour`), TOUPAC_QR_PRIVATE_KEY_PEM, UNFOLD.SIDEBAR.navigation (déclarative, sections « API & Intégrations » avec `Clés plateforme`, `Audit plateforme`).
- `config/settings/dev.py` — LOGGING doit viser `"toupac"` racine, pas `"notifications"` (hiérarchie loggers Python distincte, cf. débrief USR-3).

**Core** :
- `core/middleware.py` — TenantMiddleware (attache tenant depuis JWT/session/header, accepte slug ET UUID depuis USR-2).
- `core/models.py` — TenantModel, TenantManager (**ne filtre pas** — l'isolation est faite dans les ViewSets), UUIDv7Field, SoftDeleteMixin (**pas de manager filtrant** — `deleted_at__isnull=True` à poser explicitement).
- `core/admin.py` — TenantAdminMixin, SuperadminOnlyAdminMixin.
- `core/management/commands/seed_demo.py` — dataset démo, appelle `seed_notification_templates` en délégation.

**IAM** :
- `iam/authentication.py` — DenylistJWTAuthentication (JWT + denylist Redis).
- `iam/api_key_authentication.py` — ApiKeyAuthentication (Type 1 tenant).
- `iam/platform_authentication.py` — PlatformApiKeyAuthentication (Type 2 plateforme, résolution X-Acting-User-Email, IP allowlist, reset request.tenant d'entrée).
- `iam/platform_audit.py` — Middleware phase-réponse (PlatformAuditLog avec acting_user).
- `iam/permissions.py` — HasApiScope (Type 1).
- `iam/platform_scopes.py` — PLATFORM_AVAILABLE_SCOPES (10 scopes dont 3 write + customer:read + global:read), `platform_scope_for_domain(domain, write=True)` dérivation naturelle.
- `iam/platform_services.py` — PLATFORM_SERVICES dict (chatbot-bi, futures apps).
- `iam/scopes.py` — AVAILABLE_SCOPES, ADMIN_SCOPE, docstring en tête = doctrine `admin:*`.
- `iam/throttles.py` — ApiKeyRateThrottle, ApiKeyAdminRateThrottle.
- `iam/platform_throttles.py` — PlatformKeyRateThrottle (1000/h), ActingCustomerRateThrottle (200/h).
- `iam/forms.py` — ApiCredentialCreateForm, PlatformCredentialCreateForm.
- `iam/admin.py` — ApiCredentialAdmin, PlatformCredentialAdmin, PlatformAuditLogAdmin (filtre par acting_user), UserAdmin.
- `iam/signals.py` — provisionne service account.
- `iam/apps.py` — IamConfig.ready().
- `iam/otp.py` — helpers OTP (Redis, hash SHA256, mask_target).
- `iam/otp_views.py` — RequestOTPView, VerifyOTPView.
- `iam/customer_views.py` — CustomerMeView, CustomerCompaniesListView, MyReservationsView, MyOrdersView, MyPaymentsView, **permission `IsAuthenticatedCustomer` définie ici** (pas dans un fichier `customer_permissions.py` séparé).
- `iam/platform_views.py`, `iam/platform_urls.py` — PlatformTenantsView, PlatformHealthView.
- `iam/guardian.py` — fabrique AnonymousUser en SERVICE_ACCOUNT.
- `iam/tests/conftest.py` — fixture `superadmin` locale (pas dans conftest racine).
- `iam/tests/test_admin_api_credential_issue.py`, `test_service_accounts.py`, `test_platform_*`, `test_otp_flow.py`, `test_customer_*`, `test_acting_user_resolution.py`, `test_platform_audit_acting_user.py`.

**Notifications** :
- `notifications/catalog.py` — les 37 events déclarés.
- `notifications/priorities.py`, `channels.py` — enums StrEnum.
- `notifications/preferences.py` — 10 catégories, NEVER_OPT_OUT.
- `notifications/resolvers/base.py` — registry + décorateur + KNOWN_UNIMPLEMENTED_RESOLVERS.
- `notifications/resolvers/examples.py` — 2 exemples testés.
- `notifications/models.py` — NotificationTemplate, Notification, NotificationLog (`tenant` nullable depuis USR-2).
- `notifications/services.py` — `send_notification()` legacy, **à refondre au Ticket B**.

**Voyage / colis / billing** :
- `voyage/models.py` — Passenger avec `customer_user` (FK vers CLIENT).
- `voyage/services/qr_jwt.py` — sign/verify RS256.
- `colis/models.py` — Order avec `customer` réutilisée.
- `billing/models.py` — Invoice avec `customer_id` + `customer_type="client_user"`, constantes exposées.

**Developers** :
- `developers/views.py` — TenantDeveloperPortalView, PartnerDeveloperPortalView.
- `developers/urls.py`, `developers/partner_urls.py`.
- `developers/templates/developers/tenant_portal.html`, `partner_portal.html`, partials adaptés.

## Anti-patterns

**Source de vérité : `DECISIONS.md` à la racine du repo, 42+ entrées, groupé en 10 domaines** (acting user & B2B2C, portails et doc publique, multi-tenant et cross-tenant, auth secrets et cache, contraintes DB et cycle de vie modèle, registries et catalogues, data migrations, Python/Django, API/auth, modes de travail). À consulter avant chaque ticket qui touche à un domaine concerné.

Extraits notables souvent revus :

1. **`force_authenticate` avec middleware pré-DRF** → vrai JWT dans header Authorization.
2. **`functools.partial` pour form admin dynamique** → sous-classe dynamique.
3. **`@receiver` sans `dispatch_uid`** → double enregistrement + disconnect impossible en test.
4. **`isinstance(x, int)` accepte `bool`** → exclure explicitement.
5. **`class X(str, Enum)`** → `StrEnum` obligatoire (ruff UP042).
6. **Rename de champ via questionneur interactif** → `RenameField` à la main.
7. **Data migration ne rattrape que le passé** → lignes créées après restent orphelines.
8. **Fail-open sur émetteur indéterminable** → refuser par défaut.
9. **Sentinelle de refus qui survit à son motif** → dérivation qui échoue naturellement.
10. **`limit_choices_to` ≠ validation modèle** → `CheckConstraint` + limit_choices_to ensemble.
11. **Un middleware résout, il ne refuse pas** — corollaire : tout backend autoritaire réinitialise le contexte d'entrée.
12. **Un helper `get_or_create` ne vole pas un identifiant** — enrichit si vide, ignore silencieusement si déjà pris.
13. **`unique=True + null=True` > UniqueConstraint partielle** sur PostgreSQL (NULLS DISTINCT par défaut).
14. **`.distinct()` obligatoire sur `Q(...) | Q(...)` traversant des relations**.
15. **Serializers CLIENT en liste blanche**, jamais `__all__`.
16. **Contrainte modèle sans auditer tiers post_migrate** (django-guardian écrit un AnonymousUser).

## Modes de travail établis

- Je génère des **prompts Claude Code** exhaustifs (fichier par fichier, critères d'acceptation, anti-critères, commit prêt).
- Sonnet 4.5 gère très bien les tickets complexes tant que les décisions sont tranchées en amont. **Réserver Opus 4.7** aux tickets où plusieurs décisions produit restent à prendre ou aux refactos multi-modules exploratoires. Le chantier CLIENT global était Opus 4.7 sur les 5 tickets — justifié.
- Le dev revient avec **débrief structuré** : tableau critères passés/échoués, écarts au prompt (chacun justifié), bugs découverts en route, points à trancher.
- Je réponds aux débriefs en **valorisant les corrections** (le dev me fait souvent voir des erreurs de ma spec), puis génère le suivant.
- **Pattern warm-up avant gros chantier** — micro-tickets courts avant refonte pour lever les angles morts. Vécu : chatbot × multi-tenant, portée admin:*, sémantique user porteur, retour None silencieux, sentinelle _WRITE_REFUSED.
- **Faits présumés en tête du prompt** — 5-10 signatures/patterns supposés, validés ligne par ligne dans le débrief. Attrape mes erreurs de lecture (4+ erreurs par ticket en moyenne, toutes rattrapées avant code).
- **« N tests minimum » ≠ « exactement N tests »** — le dev complète où il voit un vide. Chantier CLIENT global : +208 tests vs 268 pré-chantier.
- **Alignement doctrine multi-endroits** — lister TOUS les fichiers où la doctrine apparaît (code, help_text, portail dev, DETTES.md, README).
- **Pas deux versions d'un même diff dans un prompt**.
- **Fail-log symétrique** — couvrir toutes les branches d'échec.
- **Discipline de découpage** sur gros chantier — ne pas laisser dériver le périmètre. Trace en dette et continue plutôt qu'élargir. Chantier CLIENT global : 5 tickets serrés au lieu d'un pavé de 5 jours.
- **Décision produit tranchée avant chantier** — quand la question est produit-critique (marketplace B2B2C vs SaaS multi-tenant), stopper les tickets courants et arbitrer avant de bâtir dessus.
- **Retirer une garantie de sécurité est un arbitrage documenté**, pas un relâchement. Un futur auditeur doit voir les conditions cumulatives qui rendent le retrait tenable.

Ces patterns et les autres sont capturés en détail dans `DECISIONS.md`.

## Ce qui vient dans le nouveau chat

Prochain ticket : **notifications-refonte-B — NotificationService v2** (Opus 4.7, ~2 jours).

Le nouveau chat démarre par la lecture des 3 fichiers de vérité (`CONTEXT_TRANSFERT.md`,
`DECISIONS.md`, `DETTES.md`), puis du module `notifications/` post-Ticket A' :
- `catalog.py` — les 37 events, comprendre la structure `NotifEvent`.
- `resolvers/base.py` — comprendre le squelette (registry, `KNOWN_UNIMPLEMENTED_RESOLVERS`).
- `preferences.py` — les 10 catégories, `NEVER_OPT_OUT`.
- `models.py` — `NotificationTemplate` enrichi, `Notification`, `NotificationLog` (`tenant` nullable depuis USR-2).
- `services.py` — `send_notification()` legacy à remplacer.

**Ce que le Ticket B doit livrer** :

1. **`NotificationService.emit(event_code, actor, context)`** — flow complet :
   - Validation contexte contre `EventCatalog[code].variables_schema`.
   - Résolution destinataires via `get_resolver(event.resolver_key)(context, tenant)`.
   - Application préférences (`user.notification_preferences.get(event.category, True)` avec bypass sur `NEVER_OPT_OUT`).
   - Idempotence (N-06) via Redis `SETEX` clé `{event_code}:{actor_id}:{target_hash}`, TTL 24h. Contrainte unique conditionnelle sur `Notification.idempotency_key` renforce au niveau DB.
   - Création `Notification` (une par destinataire) + `NotificationLog` (une par delivery attempt = destinataire × canal).
   - Enqueue Celery task par NotificationLog.

2. **Confidentialité asymétrique par canal (N-05)** — `confidentiality_masks` sur l'event s'applique en push uniquement. In-app et email portent le payload complet. Vérifier explicitement que TKT-01 `qr_payload` reste livrable via in-app/email.

3. **Fail-log symétrique** — `NotificationLog(status=failed)` pour toutes les branches d'échec :
   - Template absent (`failure_reason="no_template:..."`, déjà couvert par warmup).
   - Template présent mais cassé (Django `TemplateSyntaxError`) → `"template_error:..."`.
   - Resolver absent ou dans `KNOWN_UNIMPLEMENTED_RESOLVERS` → `"resolver_unimplemented:..."`.
   - Resolver qui lève → `"resolver_error:..."`.
   - Violation préférence NEVER_OPT_OUT → `"preference_violation:..."`.

4. **Retry différencié par canal (N-09)** — Push 3 tentatives, Email 3 tentatives, pas de bascule automatique vers SMS/WhatsApp hors OTP. Paramétré déclarativement.

5. **Refactor `send_notification()` en deprecation warning** — appelle en interne le nouveau `emit()` pour compatibilité pendant la migration, retire au Ticket F.

6. **Tests** — ~25 tests minimum (idempotence, résolution, préférences, confidentialité par canal, retry, isolation multi-tenant, tous les fail-logs, deprecation warning).

**Après Ticket B** : Tickets C (providers réels + FakePushProvider), D (endpoints in-app centre d'alertes — réutilise `IsAuthenticatedCustomer` de USR-4 pour permission composée JWT+plateforme), E1+E2 (câblage métier ~29 resolvers), F (seed templates + fusion seeders).

Puis Phase 3 : self-service user management pour admins, endpoints d'écriture CLIENT via app mobile directe, feature `add-contact-to-existing-account`.

**Rappels utiles** :
- **Architecture marketplace B2B2C posée**. TOUPAC (central) × compagnies (tenants) × CLIENT global. Le rôle CLIENT n'appartient à aucun tenant.
- **Deux types d'intégrations API** :
  - Type 1 tenant (`ApiCredential`) — émission par admin compagnie, scopes tenant.
  - Type 2 plateforme (`PlatformCredential`) — émission par superadmin TOUPAC, scopes `platform:*`, header `X-Tenant-ID` (slug) + optionnel `X-Acting-User-Email`.
- **Chatbot Toupac BI** intégrable dès qu'un tenant est créé (zéro friction) via `PlatformCredential` unique avec scopes lecture + écriture métier. Peut agir au nom d'un CLIENT via `X-Acting-User-Email`.
- **Endpoints CLIENT-scoped** (`/customer/*`) accessibles JWT direct (app mobile CLIENT) OU PlatformCredential + acting user (chatbot).
- **Portail dev split** : `/developers/` (tenant) + `/partners/developers/` (plateforme).
- **Auth CLIENT OTP-only** (`/auth/otp/request/`, `/auth/otp/verify/`), Redis, hash SHA256.
- La démo lead est bloquable en local. Le déploiement prod utilise `docker compose ... exec web python manage.py migrate` **puis** `... seed_demo` (le seed appelle `seed_notification_templates`).
