# TOUPAC — Transfert de contexte

_Généré le 2 sept 2026 après une longue session de sprint applicatif._
_Mis à jour le 5 sept 2026 après la série de tickets iam-admin (génération de clé,
démo-ready, service accounts)._
_Mis à jour le 6 sept 2026 après les Tickets notifications-warmup / A / A' — 191 tests verts,
0 régression, fondations refonte notifications posées (catalog + modèle Notification + resolvers)._
_À coller en premier message du nouveau chat Claude Opus 4.7._

## Projet et rôle

TOUPAC = TMS SaaS pour compagnies de transport ouest-africaines (UEMOA + CEDEAO).
Développement sur-mesure Django/DRF/PG-PostGIS. Le client est une compagnie
malienne (Bamako, corridors Bamako-Ségou-Bla, Bamako-Kayes-Dakar, Bamako-Bouaké-Abidjan).

Je suis **freelance en période d'essai (2 mois)**. Rôle **architecte technique
principal** côté backend. Une équipe mobile RN travaille sur Toupac Control
(app contrôleur) en parallèle, une autre équipe externe attaque bientôt un
chatbot IA (Toupac BI) qui consommera notre API.

Le projet local est à `C:\Dev\toupac_django\toupac` (accessible via
filesystem MCP). Trois fichiers de vérité à la racine :

- **`CONTEXT_TRANSFERT.md`** (ce fichier) — état du projet à jour
- **`DECISIONS.md`** — registre des patterns/anti-patterns validés au fil des tickets (créé 6 sept 2026, 18 entrées à date)
- **`DETTES.md`** — dette identifiée + section « Fonctionnel — À venir » pour les gros chantiers cadrés

## Stack et décisions d'architecture figées

- **Django 5 + DRF + GeoDjango**
- **PostgreSQL 16 + PostGIS 3.4**
- **Redis 7** (cache, throttling, denylist tokens, Celery broker)
- **Celery 5** (jobs asynchrones, beat)
- **Channels 4** installé pour WebSocket (pas encore utilisé)
- **django-unfold** pour l'admin (sidebar déclarée explicitement dans `UNFOLD["SIDEBAR"]["navigation"]`, pas auto-générée)
- **drf-spectacular** pour OpenAPI/Swagger
- **rest_framework_simplejwt** pour JWT (customisé avec denylist)
- **django-guardian** installé mais RBAC granulaire pas encore exploité
- **Docker Compose** dev (4 conteneurs) + prod (7 services + Caddy)
- **cryptography** pour RS256 des QR billets

Monolithe modulaire (pas microservices), pattern multi-tenant strict, JWT auth
interne + API key auth externe.

## Modules Django et responsabilités

10 modules, ~50 modèles au total :

| Module | Responsabilité |
|---|---|
| `core` | Mixins de base (TenantModel, UUIDv7, SoftDelete), TenantMiddleware, TenantManager, TenantAdminMixin (isolation admin + exclusion SERVICE_ACCOUNT des FK dropdowns User) |
| `iam` | Tenant (+ `get_or_create_service_account()`), User (custom AbstractBaseUser, 8 rôles dont `SERVICE_ACCOUNT`, + `notification_preferences` JSONField), ApiCredential, AuditLog, UserDevice, scopes API, signal `post_save(Tenant)` d'auto-provisioning bot |
| `fleet` | VehicleType, Vehicle, Driver, VehicleDocument, Fleet, FleetVehicle |
| `geo` | Place (tenant nullable pour places publiques), Zone |
| `workflow` | WorkflowDefinition, State, Transition, Hook (configurable en DB) |
| `voyage` | Route, RouteStop, Schedule, SeatMap, Trip, TripStop, Passenger, Reservation, Controller, ControlSession, ControlEvent (batch offline), Anomaly, Incident, CashEntry, PassengerAccessLog, LuggagePolicy |
| `colis` | Order, Parcel, DeliveryTask, ProofOfDelivery |
| `billing` | PriceList, PriceRule, Invoice, InvoiceLine, Payment (Intouch mobile money sandbox) |
| `tracking` | Position (pas TenantModel, BigAutoField pour volumétrie), Geofence, GeofenceEvent, TrackingLink |
| `notifications` | **Refonte en cours selon charte TOUPAC ONE.** Tickets warmup + A + A' fermés. Modèles : `NotificationTemplate` (rendu par event_code/channel/lang/tenant), `Notification` (item du centre d'alertes, 1 par recipient_user), `NotificationLog` (delivery attempts). Catalog déclaratif (`catalog.py`, 37 events), système de resolvers (`resolvers/`), catégories de préférences (`preferences.py`). Service (`NotificationService.emit()`) refondu au Ticket B (à venir). |
| `developers` | Portail dev statique servi par Django |

## Périmètre produit confirmé par le lead

Suite "TOUPAC ONE" = 7 apps, mais **notre équipe backend produit uniquement** :
- **Toupac 360** (backoffice, Django admin aujourd'hui, console React V1.5)
- **Toupac Control** (app mobile contrôleur, dev RN en cours)
- **Toupac Driver** (app mobile chauffeur, à venir)
- **App client fusionnée Cargo + Go** (voyages + colis, à venir)

Nous **préparons l'API** consommée par :
- **Toupac CRM** = intégrations ERP tierces (Sage, Odoo)
- **Toupac BI** = chatbot IA développé par équipe externe qui a gagné le marché

## Décisions produit tranchées par le lead (rendez-vous du 2 sept 2026)

1. **SMS et WhatsApp = strictement OTP-only**. Tous les autres canaux → Push + In-app + Email selon la charte notifications TOUPAC ONE.
2. **7 apps = vision cible, pas V1**. On construit un backend unifié + 4 fronts (voir périmètre ci-dessus).
3. **Tramingo = intégration (pas remplacement par Traccar)**. Doc API v1.7 en main, polling REST classique, OAuth 2.0 password grant, événements pré-calculés dispos (excès vitesse, sortie zone, etc.).
4. **Coordination Dispatcher↔Chauffeur = notifications unidirectionnelles avec accusés de lecture** (pas de messagerie bidirectionnelle en V1). Traçabilité préservée. Porte ouverte architecture pour rabattre vers option messagerie plus tard.

## Décisions doctrine IAM tranchées (3-5 sept 2026)

Clarifications produites en même temps que les 3 tickets iam-admin. Elles cadrent
le comportement du système d'accès API pour la suite du projet.

1. **Scope `admin:*` = TOUPAC interne uniquement**. Réservé aux intégrations
   internes TOUPAC (outillage superadmin, adaptateurs Toupac CRM maintenus par
   TOUPAC). Aucun tenant client n'a de cas d'usage légitime — les compagnies
   ouest-africaines cibles n'ont pas d'ERP maison développé sur-mesure. **Blocage
   dur** dans `ApiCredentialCreateForm.clean_scopes()` pour tout émetteur
   non-superadmin. Fail-closed quand `_request` est None. Docstring `iam/scopes.py`
   et portail `/developers/` alignés sur cette formulation unique.

2. **Modèle chatbot × multi-tenant = N clés, une par tenant abonné**.
   Le chatbot Toupac BI est un partenaire externe unique côté codebase, mais
   consomme N clés API (une par compagnie qui souscrit au service). Chaque tenant
   admin émet sa propre clé depuis son admin Django, avec scopes explicites
   (`voyage:read`, `colis:read`, etc.) — jamais `admin:*`. Le chatbot maintient
   en interne le mapping `tenant → clé`. `ApiKeyAuthentication` résout le tenant
   depuis la clé et attache `request.tenant`.

3. **Service account par tenant**. Chaque tenant est doté automatiquement
   (signal `post_save(Tenant)`) d'un compte technique : email
   `api-bot@<tenant.slug>.internal`, rôle `User.Role.SERVICE_ACCOUNT`,
   `set_unusable_password()`, `is_active=True`, `is_staff=False`, aucune
   permission Django, aucun groupe. **Toutes les clés API du tenant pointent
   vers ce compte** — le champ `user` n'existe plus dans le form admin.
   Le service account est invisible dans les listings de users pour les tenant
   admins (superadmin le voit pour diagnostic), et exclu des FK dropdowns User
   partout dans l'admin (`TenantAdminMixin._scoped_related_queryset` filtre
   `role=SERVICE_ACCOUNT`). Auto-guérison : si le bot est supprimé,
   `Tenant.get_or_create_service_account()` le recrée à l'émission suivante.

4. **Séquencement gros chantiers IAM**. Refonte notifications d'abord.
   Self-service user management (permettre aux admins de compagnie de créer
   leurs propres utilisateurs) après, avec durcissement `UserAdmin` contre
   l'escalade de privilèges. Tracé en `DETTES.md` section « Fonctionnel — À venir ».

## Décisions doctrine notifications tranchées (5-6 sept 2026)

Clarifications produites au fil de la refonte (Tickets warmup, A, A'). Elles
cadrent la conception du module notifications pour la suite (Tickets B → F).

1. **Convention `notif.{domaine}.{evenement}.{version}`**. Verrouillée par la
   charte TOUPAC ONE. Codes canoniques choisis :
   - `notif.order.*` (pas `notif.command.*` — corrigé en A' pour éviter la
     confusion CLI/impératif). Couvre voyage.Reservation et colis.Order via
     `context.order_type = "reservation" | "parcel"`.
   - `notif.platform.system_incident.v1` (pas `notif.si.*` — sigle
     franco-français opaque pour intégrateur anglophone, corrigé en A').

2. **Push + In-app OBLIGATOIRES sur tous les événements non-OTP**. Email
   selon cas (adresse vérifiée + préférences). SMS/WhatsApp uniquement OTP.
   32/37 events en Push, 18/37 en Email, 3/37 en SMS, 3/37 en WhatsApp (secours OTP).

3. **EventCatalog en code = source unique de vérité**. `notifications/catalog.py`
   déclare les 37 events avec `NotifEvent(code, charte_id, label, priority,
   category, default_channels, variables, resolver_key, requires_ack,
   confidentiality_masks)`. Validation à l'import (voir DECISIONS.md
   « Registries et catalogues déclaratifs »). Le portail dev, l'admin, le
   service et les tests s'y appuient tous. Évolution d'un event = nouvelle
   version (`.v1` → `.v2`), pas édition en place.

4. **Service explicite `NotificationService.emit()`, pas signals Django**.
   Le code métier appelle `NotificationService.emit(event_code, actor, context)`.
   Le service valide le contexte, résout les destinataires via le resolver
   déclaré, applique préférences et idempotence, crée les Notifications et
   NotificationLogs, enqueue Celery. Les signals restent réservés à l'audit
   passif, pas à la comm métier — debug catastrophique en prod si utilisés
   ici.

5. **Une `Notification` = un `recipient_user`, pas un groupe**. Un event
   « broadcast rôle » (ex: DSP-01 vers tous les dispatchers) génère N
   Notifications individuelles au moment de l'émission. `read_at` / `acked_at`
   par-user naturellement. Les champs `trigger_scope` (user/role/tenant) et
   `trigger_role` (str) tracent la source pour audit.

6. **`variables_schema` en format Python natif, pas JSON Schema ni Pydantic**.
   Format `{"var_name": VariableSpec(type="string|int|float|datetime|url|uuid",
   required=bool, max_length=int?)}`. Validation `validate_context()` en Python
   natif. Zéro dépendance PyPI. Piège attrapé : `isinstance(x, int)` accepte
   `bool`, exclure explicitement (voir DECISIONS.md).

7. **Préférences user via `User.notification_preferences` (JSONField)**.
   Dict de catégories opt-in/opt-out (`{"marketing": False, "trip_updates": True}`).
   Catégories reconnues déclarées dans `notifications/preferences.py`. Absence
   de clé = opt-in par défaut. Trois catégories jamais opt-out (safety net) :
   `otp`, `security`, `critical_ops`. INC-02 (incident résolu) est en
   `critical_ops` par symétrie avec INC-01 (asymétrie corrigée en A').

8. **Confidentialité (N-05) via masques par canal**. `confidentiality_masks`
   sur l'event du catalog liste les variables à masquer côté push (pas de
   montant, pas d'OTP, pas d'ID passager dans le push). **Asymétrique par
   canal** : le push masque, l'in-app et l'email portent le payload complet
   (à intégrer explicitement au Ticket B — soulevé par débrief A sur TKT-01
   qr_payload, le billet doit rester livrable ailleurs).

## État du sprint applicatif au 6 sept 2026

**Ce qui est fait (base historique)** :
- Feature `session_id` batch offline (contrat verrouillé avec dev RN)
- QR billets RS256 end-to-end + endpoint public `/qr-public-key/`
- Tests critiques : auth (JWT + denylist), multi-tenant isolation API, workflow transitions, paiement Intouch mocké
- 2 dettes sécu multi-tenant fermées (Payment scoping, activity_transition scoping)
- Fuite admin cross-tenant fermée + 2 bonus (UserDevice, WorkflowState)
- Exposition superadmin dans dropdowns User fermée
- Seed démo réaliste 2 tenants (Sahel Express, Dem Dikk) — commande `seed_demo` idempotente
- Access token denylist Redis (dette Sprint 2 §4.19 fermée)
- TenantMiddleware TRIAL débloqué
- **Fondations API publique** : 15 scopes, fail-closed via permission globale, rate limiting par clé (1000/h ou 10000/h admin), portail `/developers/` statique, extension spectacular pour X-API-Key

**Livré dans la série iam-admin (3-5 sept 2026)** :
- **Génération de clé API depuis Django Admin** — form custom avec multi-select scopes, révélation one-shot avec TTL 5 min, AuditLog sans secret, test end-to-end contre l'API réelle.
- **Démo-ready** — 4 permissions `*_apicredential` ajoutées au groupe staff, refus dur `admin:*` pour non-superadmin, docstring `iam/scopes.py` réécrit + portail dev aligné.
- **Service accounts** — nouveau rôle `SERVICE_ACCOUNT`, signal auto-provisioning, data migration backfill, form sans champ user, filtrage bots dans dropdowns.

**Livré dans la série notifications (5-6 sept 2026)** :
- **Warm-up (notifications-warmup)** — 2 fixes préparatoires : retour `None` silencieux de `send_notification()` remplacé par `NotificationLog(status=failed)` (N-08 traçabilité), canal `IN_APP` ajouté à l'enum `Channel`. Package `tests/` initialisé.
- **Ticket A (notifications-refonte-A)** — Fondations. `NotificationTemplate.event_type` → `event_code` (rename + backfill). Ajout de `title_template`, `action_url_template`. Retrait de `subject`. Nouveau modèle `Notification` (item centre d'alertes, 1 par user, idempotency_key contraint par unique conditionnelle). `User.notification_preferences` (JSONField). Catalog `notifications/catalog.py` avec les 37 events. Système de resolvers (`notifications/resolvers/`) : registry + décorateur + validation croisée + 2 exemples testés. `notifications/preferences.py` (10 catégories, dont 3 « never opt-out »). `NotificationsConfig.ready()` charge catalog + resolvers. 4 migrations : notifications 0003 (rename) + 0004 (enrich + Notification) + 0005 (data backfill + retrait subject) + iam 0005 (notification_preferences). Second seeder (`seed_notification_templates`) aligné en collatéral pour éviter collision unique.
- **Ticket A' (notifications-refonte-A')** — 4 correctifs post-A : `notif.command.*` → `notif.order.*` (+ variable `order_type`), `notif.si.*` → `notif.platform.*`, INC-02 → `critical_ops`, resolver_keys `command.*` → `order.*`. Migration 0005 éditée sur place (pas de nouvelle migration).
- **Compteur** : 191 tests verts (139 base + 2 warmup + 50 Ticket A + 0 Ticket A' — tests data-driven survivent aux renames par construction).
- **Nouveau fichier `DECISIONS.md`** à la racine — registre des patterns/anti-patterns validés, 18+ entrées à date, groupé en 6 domaines.

**Ce qui reste (Phase 2 immédiate)** :
- **Ticket B — NotificationService v2 (Opus 4.7, ~2 jours)** — Refonte du service selon charte. `emit(event_code, actor, context)` remplace `send_notification()`. Validation contexte, résolution destinataires, application préférences (N-02), idempotence (N-06) via Redis, création Notification + NotificationLog, enqueue Celery per delivery. Retry différencié par canal (N-09 : Push 3×, Email 3×, pas de bascule SMS/WhatsApp). **Intègre 2 points du débrief A** : confidentialité asymétrique par canal (push masqué, in-app/email complets), fail-log symétrique (couvre template absent, template cassé, resolver absent, resolver qui lève).
- **Tickets C/D/E1/E2/F** — Sonnet 4.5 chacun, ~1 jour. C: providers réels (FakePushProvider en attendant FCM). D: endpoints in-app centre d'alertes. E1: câblage voyage + paiement + colis (~15 resolvers). E2: câblage restant (~14 resolvers — le Ticket E s'est révélé ~2× plus lourd que budgété initialement à cause de la déduplication réelle des resolvers). F: seed des 37 templates système + fusion des deux seeders actuels de notifications.

**Micro-tickets courts prêts à insérer entre 2 gros tickets** :
- **Route↔RouteStop cohérence** (~30 min) — validation `Route.clean()`
- **/qr-public-key/ warning au lieu de crash** (~20 min)

**Phases suivantes** (dans l'ordre) :
- Phase 2 (suite) : intégration Tramingo (polling REST, mapping IMEI→Vehicle, événements pré-calculés → notifs GPS-01/02), intégration FCM/APNs (canal Push réel remplace FakePushProvider), import Excel client (véhicules, chauffeurs, lignes), enrichissements modèle (colis.ForbiddenGoods, Route.category national/international, grille bagage), ré-alignement seed (marques YUTONG, corridors Mali)
- Phase 3 : self-service user management pour admins de compagnie (durcissement `UserAdmin` anti-escalade, workflow email d'invitation vs password direct — cadrage détaillé dans `DETTES.md`), puis modules métier découverts via Excel (Maintenance, Fidélisation, Contrats Partenaires, Suivi carburant)
- Phase 4 : webhooks sortants HMAC (Surface B ERP), Metabase branché reporting
- Phase 5 : MFA TOTP admin, Import CSV commandes, micro-dettes restantes

## Conventions de code établies

**Tests** :
- pytest + pytest-django avec `conftest.py` à la racine (fixtures partagées : `tenant_a`, `tenant_b`, `user_admin_a`, `user_admin_b`, `user_dispatcher_a`, `user_controller_a`, `authenticated_client`, `_isolated_throttle_cache` autouse)
- Un package `tests/` par module avec `test_*.py`
- Utiliser **de vrais JWT** pour tester l'auth (pas `force_authenticate` qui court-circuite TenantMiddleware)
- Tests admin : `Client()` + `client.force_login(user)`, PAS `APIClient`. Helper local `grant_admin_permissions(user)` (permissions par app_label)
- Assertions sur le **contenu**, pas juste le status code (pattern « test qui passe pour la mauvaise raison »)
- Assertions HTML sur UUID/attributs, pas sur labels affichés
- **Test end-to-end obligatoire** pour toute émission de credential/token (voir DECISIONS.md « Test end-to-end sur toute émission »)
- **Data migration non triviale = test dédié** via `importlib.import_module` + `apps.get_model` (exceptions documentées dans DECISIONS.md)
- **Tests data-driven sur invariants** — itérer sur `all_events()`, `all_scopes()`, etc. plutôt qu'écrire des codes en dur. Les renames ne cassent pas les tests. Voir DECISIONS.md « Tests data-driven sur invariants ».

**Ruff** :
- Config dans `pyproject.toml` avec `select = ["E", "F", "W", "I", "B", "C4", "UP", "RUF"]`
- `RUF012` désactivé (idiome Django/DRF pour attributs de classe)
- `EXE002` non sélectionné (faux positif Windows bind-mount)
- `E402` ignoré sur `config/settings/*.py`
- **`UP042`** (StrEnum) actif — `class X(str, Enum)` est un anti-pattern, utiliser `StrEnum` (voir DECISIONS.md)

**DETTES.md, DECISIONS.md, CONTEXT_TRANSFERT.md — répartition** :
- **DETTES.md** : dette identifiée à traiter (Sécurité, Modèle, Ergonomie / robustesse, Ops, Fonctionnel, Fonctionnel — À venir, Tests / perf)
- **DECISIONS.md** : patterns/anti-patterns validés au fil des tickets, groupé en 6 domaines. Un pattern y entre après validation par un débrief.
- **CONTEXT_TRANSFERT.md** (ce fichier) : état du projet, doctrine produit, décisions structurantes, plan de séquencement. Pointe vers DECISIONS.md pour le détail des patterns.

**Commits** :
- Convention `feat(scope): ...`, `fix(scope): ...`, `chore(scope): ...`, `test(scope): ...`, `docs: ...`, `refactor(scope): ...`
- Body avec contexte + résultats chiffrés + refs vers tickets/dettes
- 1 commit par ticket, atomique

## Fichiers-clés à connaître dans le repo

**Racine** :
- `CONTEXT_TRANSFERT.md`, `DECISIONS.md`, `DETTES.md` — les 3 fichiers de vérité
- `conftest.py` — fixtures partagées

**Config** :
- `config/settings/base.py` — REST_FRAMEWORK config (auth chain, throttles), TOUPAC_QR_PRIVATE_KEY_PEM, UNFOLD.SIDEBAR.navigation (déclarative, pas auto)

**Core** :
- `core/middleware.py` — TenantMiddleware (attache tenant depuis JWT/session/header)
- `core/models.py` — TenantModel, TenantManager, UUIDv7Field, SoftDeleteMixin
- `core/admin.py` — TenantAdminMixin, SuperadminOnlyAdminMixin (le mixin écrase tenant en save_model, ajoute tenant aux readonly hors superadmin, filtre queryset, exclut SERVICE_ACCOUNT des FK User)
- `core/management/commands/seed_demo.py` — génération dataset démo, groupe staff avec permissions ciblées `*_apicredential`

**IAM** :
- `iam/authentication.py` — DenylistJWTAuthentication (JWT + denylist Redis)
- `iam/api_key_authentication.py` — ApiKeyAuthentication (résout tenant depuis credential, retourne `(credential.user, credential)`)
- `iam/permissions.py` — HasApiScope (permission globale, fail-closed)
- `iam/scopes.py` — dict AVAILABLE_SCOPES, ADMIN_SCOPE, docstring en tête = doctrine `admin:*`
- `iam/throttles.py` — ApiKeyRateThrottle, ApiKeyAdminRateThrottle (mutuellement exclusifs, rate par requête)
- `iam/forms.py` — ApiCredentialCreateForm (multi-select scopes, PAS de champ user, refus admin:* pour non-superadmin, injection request via sous-classe dynamique dans admin)
- `iam/admin.py` — ApiCredentialAdmin (save_form délègue à issue() + AuditLog, response_add pose session flash, reveal_view avec check credential_id + TTL, UserAdmin masque SERVICE_ACCOUNT hors superadmin)
- `iam/signals.py` — `@receiver(post_save, sender=Tenant, dispatch_uid=...)` → provisionne service account
- `iam/apps.py` — IamConfig.ready() importe schema + signals
- `iam/tests/test_admin_api_credential_issue.py` — 13 tests admin
- `iam/tests/test_service_accounts.py` — 8 tests

**Notifications** :
- `notifications/catalog.py` — les 37 events déclarés, `NotifEvent` dataclass frozen, `register()`, `get_event()`, `all_events()`, `events_by_family()`, `validate_context()`
- `notifications/priorities.py`, `channels.py` — enums StrEnum (Priority, Channel)
- `notifications/preferences.py` — 10 catégories (`CATEGORY_OTP`, `CATEGORY_CRITICAL_OPS`, `CATEGORY_TRIP_UPDATES`, etc.), `NEVER_OPT_OUT` = 3 catégories jamais désactivables
- `notifications/resolvers/base.py` — `Resolver`, `ResolvedRecipient`, `register_resolver`, `KNOWN_UNIMPLEMENTED_RESOLVERS`
- `notifications/resolvers/examples.py` — 2 exemples testés (`_example.customer_from_context`, `_example.dispatchers_of_tenant`)
- `notifications/models.py` — `NotificationTemplate` (rendu par event_code/channel/lang/tenant), `Notification` (item centre d'alertes), `NotificationLog` (delivery attempts)
- `notifications/services.py` — `send_notification()` legacy, **à refondre au Ticket B**

**Voyage / autres** :
- `voyage/services/qr_jwt.py` — sign/verify RS256 avec fallback éphémère dev
- `voyage/services/event_processor.py` + `handlers/` — traitement des batchs offline
- `developers/` — portail dev statique, aligné sur doctrine admin:* + paragraphe « Compte de service »

## Anti-patterns

**Source de vérité : `DECISIONS.md` à la racine du repo, 18+ entrées, groupé en 6 domaines** (registries, data migrations, Python/Django, API/auth, multi-tenant, modes de travail). À consulter avant chaque ticket qui touche à un domaine concerné.

Extraits notables souvent revus :

1. **`force_authenticate` avec middleware pré-DRF** → vrai JWT dans header Authorization
2. **`functools.partial` pour form admin dynamique** → sous-classe dynamique (`type(name, (form,), {"_request": req})`)
3. **`@receiver` sans `dispatch_uid`** → double enregistrement + disconnect impossible en test
4. **`set_unusable_password()` inaccessible via `apps.get_model`** → `make_password(None)` en data migration
5. **`isinstance(x, int)` accepte `bool`** → exclure `isinstance(x, bool)` explicitement dans tout validateur numérique
6. **`class X(str, Enum)` produit `"X.MEMBER"` au lieu de `"member"`** → `StrEnum` obligatoire (ruff UP042)
7. **Rename de champ via questionneur interactif** → `RenameField` à la main, jamais laisser Django deviner
8. **Data migration ne rattrape que le passé** → lignes créées après la migration restent orphelines. Ne pas re-play, écrire une nouvelle migration.
9. **Fail-open sur émetteur indéterminable** → si contexte émetteur `None`, refuser par défaut
10. **Doctrine sécurité en un seul endroit** → lister tous les fichiers où elle apparaît, aligner d'un coup
11. **Registre surjectif sans arbitre** → deux valeurs héritées → même cible sous unique = plantage en prod, passe en dev vide. Auditer données réelles avant `UPDATE`.

## Modes de travail établis

- Je génère des **prompts Claude Code** exhaustifs (fichier par fichier, critères d'acceptation, anti-critères, commit prêt)
- Sonnet 4.5 gère très bien même des tickets complexes (refonte modèle + signal + migration + tests) tant que les décisions sont tranchées en amont. Réserver Opus 4.7 aux tickets où **plusieurs décisions produit restent à prendre** ou aux refactos multi-modules exploratoires.
- Le dev revient avec **débrief structuré** : tableau critères passés/échoués, écarts au prompt (chacun justifié), bugs découverts en route, points à trancher
- Je réponds aux débriefs en **valorisant les corrections** (le dev me fait souvent voir des erreurs de ma spec), puis génère le suivant
- **Pattern warm-up avant gros chantier** — 1-3 micro-tickets courts avant refonte. Vécu : chatbot × multi-tenant, portée admin:*, sémantique user porteur, retour `None` silencieux — tous levés en warm-up.
- **Faits présumés en tête du prompt** — 5-10 signatures/patterns supposés, validés ligne par ligne dans le débrief. Attrape mes erreurs de lecture.
- **« N tests minimum » ≠ « exactement N tests »** — le dev complète où il voit un vide. Ticket A : 191 tests au lieu de 156 attendus.
- **Alignement doctrine multi-endroits** — lister TOUS les fichiers où la doctrine apparaît (code, help_text, portail dev, DETTES.md, README). Sinon dette de sync inévitable.
- **Pas deux versions d'un même diff dans un prompt** — soit un bloc unique, soit une section « choix A ou B, ma pref X ». Éviter les mini-snippets qui divergent d'un bloc suggéré (piège vécu à notifications-warmup).
- **Fail-log symétrique** — un mécanisme de traçabilité d'erreur couvre toutes les branches d'échec, pas seulement celle qui a motivé le ticket (ressource absente, ressource cassée, ressource inapplicable).

Ces patterns et les autres sont capturés en détail dans `DECISIONS.md`.

## Ce qui vient dans le nouveau chat

Prochain ticket : **notifications-refonte-B — NotificationService v2** (Opus 4.7, ~2 jours).

Le nouveau chat démarre par la lecture des 3 fichiers de vérité (`CONTEXT_TRANSFERT.md`,
`DECISIONS.md`, `DETTES.md`), puis du module `notifications/` post-Ticket A' :
- `catalog.py` — les 37 events, comprendre la structure `NotifEvent`
- `resolvers/base.py` — comprendre le squelette (registry, `KNOWN_UNIMPLEMENTED_RESOLVERS`)
- `preferences.py` — les 10 catégories, `NEVER_OPT_OUT`
- `models.py` — `NotificationTemplate` enrichi, `Notification`, `NotificationLog`
- `services.py` — `send_notification()` legacy à remplacer

**Ce que le Ticket B doit livrer** :

1. **`NotificationService.emit(event_code, actor, context)`** — flow complet :
   - Validation contexte contre `EventCatalog[code].variables_schema`
   - Résolution destinataires via `get_resolver(event.resolver_key)(context, tenant)`
   - Application préférences (`user.notification_preferences.get(event.category, True)` avec bypass sur `NEVER_OPT_OUT`)
   - Idempotence (N-06) via Redis `SETEX` clé `{event_code}:{actor_id}:{target_hash}`, TTL 24h. Contrainte unique conditionnelle sur `Notification.idempotency_key` renforce au niveau DB.
   - Création `Notification` (une par destinataire) + `NotificationLog` (une par delivery attempt = destinataire × canal)
   - Enqueue Celery task par NotificationLog

2. **Confidentialité asymétrique par canal (N-05)** — `confidentiality_masks` sur l'event s'applique en push uniquement. In-app et email portent le payload complet. Ne PAS lister les masques comme un filtre global — c'est un filtre côté rendu push, pas côté données. Vérifier explicitement que TKT-01 `qr_payload` reste livrable via in-app/email (débrief A).

3. **Fail-log symétrique** — le service crée un `NotificationLog(status=failed)` pour toutes les branches d'échec, pas seulement « template absent » :
   - Template absent (déjà couvert par warmup, `failure_reason="no_template:..."`)
   - Template présent mais cassé (Django `TemplateSyntaxError`) → `failure_reason="template_error:..."`
   - Resolver absent ou dans `KNOWN_UNIMPLEMENTED_RESOLVERS` → `failure_reason="resolver_unimplemented:..."`
   - Resolver qui lève → `failure_reason="resolver_error:..."`
   - User opt-out inattendu (catégorie `NEVER_OPT_OUT` mais préférence `False` en base — probablement corruption) → `failure_reason="preference_violation:..."`

4. **Retry différencié par canal (N-09)** — Push 3 tentatives, Email 3 tentatives, pas de bascule automatique vers SMS/WhatsApp hors OTP. Paramétré déclarativement (probablement dans `channels.py` ou `catalog.py`), pas en constants dispersés.

5. **Refactor `send_notification()` en deprecation warning** — appelle en interne le nouveau `emit()` pour compatibilité pendant la migration, retire au Ticket F.

6. **Tests** — ~25 tests minimum (idempotence, résolution, préférences, confidentialité par canal, retry, isolation multi-tenant, tous les fail-logs, deprecation warning).

**Après Ticket B** : Tickets C (providers réels), D (endpoints in-app), E1+E2 (câblage métier ~29 resolvers dédupliqués), F (seed templates + fusion des deux seeders). Puis self-service user management pour admins de compagnie (Phase 3).

**Rappels utiles** :
- L'équipe chatbot BI attaque après stabilisation de l'API. Le catalog + `/developers/` sont pour eux.
- La démo lead est déjà bloquable en local (créer une clé en admin d'une compagnie fonctionne, service accounts en place, endpoints publics répondent).
- Le déploiement prod utilise `docker compose ... exec web python manage.py migrate` **puis** `... seed_demo` (le seed re-fixe les permissions du groupe staff après un changement de composition).
