# TOUPAC — Transfert de contexte

_Généré le 2 sept 2026 après une longue session de sprint applicatif._
_MàJ 5 sept 2026 après la série iam-admin._
_MàJ 6 sept 2026 après les Tickets notifications warmup / A / A' — 191 tests._
_MàJ 7 sept 2026 après le chantier CLIENT global (iam-platform-credentials + USR-1 à USR-4) — 476 tests, architecture marketplace B2B2C posée._
_MàJ 8 sept 2026 après la refonte notifications complète (Tickets B / C / D) + correctif ConsoleProvider + cross-check charte notifications TOUPAC ONE — 637 tests, plan complet A→F cadré._
_À coller en premier message du nouveau chat Claude Opus 4.7._

## Projet et rôle

TOUPAC = TMS SaaS pour compagnies de transport ouest-africaines (UEMOA + CEDEAO).
Développement sur-mesure Django/DRF/PG-PostGIS. Le client est une compagnie
malienne (Bamako, corridors Bamako-Ségou-Bla, Bamako-Kayes-Dakar, Bamako-Bouaké-Abidjan).

Je suis **freelance en période d'essai (2 mois)**. Rôle **architecte technique
principal** côté backend. Une équipe mobile RN travaille sur Toupac Control
(app contrôleur) en parallèle, une équipe partenaire externe attaque bientôt un
chatbot IA (Toupac BI) qui consommera notre API — les fondations posées au
chantier CLIENT global (PlatformCredential + acting user) sont prêtes.

Le projet local est à `C:\Dev\toupac_django\toupac` (accessible via
filesystem MCP). Trois fichiers de vérité à la racine :

- **`CONTEXT_TRANSFERT.md`** (ce fichier) — état du projet à jour
- **`DECISIONS.md`** — registre des patterns/anti-patterns validés (~50 entrées, 12 domaines)
- **`DETTES.md`** — dette identifiée + section « Fonctionnel — À venir » pour les gros chantiers cadrés

Une note de design vit à part :
- **`docs/design/platform-credentials.md`** — architecture PlatformCredential Type 1 / Type 2, OAuth 2.0 CC écarté, mitigations sécu.

## Stack et décisions d'architecture figées

- **Django 5 + DRF + GeoDjango**
- **PostgreSQL 16 + PostGIS 3.4**
- **Redis 7** (cache, throttling, denylist tokens, storage OTP, Celery broker, idempotency notifs)
- **Celery 5** (jobs asynchrones, beat — beat pas encore utilisé, sera pour scheduler notifs T-24h/J-30)
- **Channels 4** installé pour WebSocket (pas encore utilisé)
- **django-unfold** pour l'admin (sidebar déclarative dans `UNFOLD["SIDEBAR"]["navigation"]`)
- **drf-spectacular** pour OpenAPI/Swagger (`spectacular --validate` en routine pre-merge depuis Ticket D)
- **rest_framework_simplejwt** pour JWT (customisé avec denylist)
- **django-guardian** installé — `AnonymousUser` provisionné avec rôle `SERVICE_ACCOUNT` via `iam/guardian.py` (USR-1)
- **Docker Compose** dev (4 conteneurs) + prod (7 services + Caddy)
- **cryptography** pour RS256 des QR billets

Monolithe modulaire (pas microservices). **Architecture marketplace B2B2C** :
TOUPAC (plateforme centrale) × compagnies (tenants) × passagers/expéditeurs
(CLIENT global). Multi-tenant strict pour les rôles opérationnels compagnies,
tenantless pour le rôle CLIENT.

**Stack frontend backoffice (à valider avec le lead avant Chantier BACKOFFICE-BOOTSTRAP)** :
- **Vite + React 18 + TypeScript strict** (pas Next.js — SPA authentifiée, pas de SSR utile)
- **Tailwind CSS + shadcn/ui + lucide-react** (composants copiables, dark mode natif)
- **TanStack Query v5 + Axios** (server state, cache, refetch, JWT + tenant header interceptors)
- **React Hook Form + Zod** (formulaires performants + validation TS-first)
- **React Router v6** (stable, connu de tous)
- **TanStack Table v8** (headless, sort/filter/pagination custom)
- **react-leaflet + OSM** pour cartes (Phase D Tramingo) — souverain, gratuit
- **Recharts** pour dashboard (React-first, suffisant)
- **openapi-typescript-codegen** pour générer un client TS typé depuis `/schema/` — game-changer, aucune erreur de champ manquant possible
- **react-i18next** (FR par défaut, EN en préparation)
- **Repo séparé** `toupac_frontend` au même niveau que `toupac_django`
- **Design pattern** : inspiration Fleetbase console (sidebar sombre, tables denses, actions inline, palette pro) — pas de Figma existant

## Modules Django et responsabilités

10 modules, ~50 modèles au total :

| Module | Responsabilité |
|---|---|
| `core` | Mixins de base (TenantModel, UUIDv7, SoftDelete), TenantMiddleware (accepte `X-Tenant-ID` en slug OU UUID depuis USR-2), TenantManager (ne filtre pas — l'isolation est faite dans les ViewSets), TenantAdminMixin. `SoftDeleteMixin` n'a pas de manager filtrant. |
| `iam` | Tenant, User (8 rôles + CLIENT tenantless depuis USR-1), `get_or_create_service_account()`, `get_or_create_platform_bot()`, `get_or_create_client()`. **Deux types d'intégrations API** : `ApiCredential` (par tenant, USR-0 iam-admin) + `PlatformCredential` (par service plateforme, série iam-platform + USR-4). `PlatformAuditLog` avec `acting_user`. OTP (`otp.py`, `otp_views.py`), endpoints CLIENT (`customer_views.py`, `customer_notifications_views.py`). |
| `fleet` | VehicleType, Vehicle, Driver, VehicleDocument, Fleet, FleetVehicle |
| `geo` | Place (tenant nullable pour places publiques), Zone |
| `workflow` | WorkflowDefinition, State, Transition, Hook (configurable en DB) |
| `voyage` | Route, RouteStop, Schedule, SeatMap, Trip, TripStop, **Passenger + Passenger.customer_user (USR-3)**, Reservation, Controller, ControlSession, ControlEvent, Anomaly, Incident, CashEntry, PassengerAccessLog, LuggagePolicy |
| `colis` | Order (`customer` FK vers User CLIENT global), Parcel, DeliveryTask, ProofOfDelivery |
| `billing` | PriceList, PriceRule, Invoice (`customer_id` UUID + `customer_type="client_user"`), InvoiceLine, Payment (Intouch mobile money sandbox) |
| `tracking` | Position, Geofence, GeofenceEvent, TrackingLink (modèles prêts, Tramingo pas encore branché) |
| `notifications` | **Refonte complète (Tickets warmup/A/A'/B/C/D bouclés).** Modèles : `NotificationTemplate`, `Notification`, `NotificationLog` (tenant nullable depuis USR-2). Catalog 37 events (`catalog.py`), resolvers (`resolvers/`), catégories préférences (`preferences.py`). `NotificationService.emit()` refondu (Ticket B). Factory providers configurable via `settings.NOTIFICATION_PROVIDERS` (Ticket C). 5 endpoints centre d'alertes CLIENT (Ticket D). **~29 resolvers métier restent à câbler (Tickets E1+E2 fusionnés).** |
| `developers` | **Portail split (USR-4)** : `/developers/` (mode tenant ApiCredential) + `/partners/developers/` (mode plateforme PlatformCredential + acting user). |

## Périmètre produit confirmé par le lead

Suite "TOUPAC ONE" = 7 apps, mais **notre équipe backend produit uniquement** :
- **Toupac 360** (backoffice — chantier backoffice frontend à démarrer après Phase B)
- **Toupac Control** (app mobile contrôleur, dev RN en cours)
- **Toupac Driver** (app mobile chauffeur, à venir)
- **App client fusionnée Cargo + Go** (voyages + colis, à venir — auth OTP CLIENT prête, endpoints `/customer/my-*` prêts, centre d'alertes prêt)

Nous **préparons l'API** consommée par :
- **Toupac CRM** = intégrations ERP tierces (Sage, Odoo) — Type 2 plateforme
- **Toupac BI** = chatbot IA développé par équipe externe — Type 2 plateforme, fondations posées

## Décisions produit tranchées (rendez-vous du 2 sept 2026)

1. **SMS et WhatsApp = strictement OTP-only**. Push + In-app + Email selon la charte.
2. **7 apps = vision cible, pas V1**.
3. **Tramingo = intégration (pas remplacement par Traccar)**. Doc API v1.7 en main.
4. **Coordination Dispatcher↔Chauffeur = notifications unidirectionnelles avec ack** (pas messagerie bidirectionnelle V1).

## Décisions doctrine IAM (3-5 sept 2026)

1. **Scope `admin:*` = TOUPAC interne uniquement**. Fail-closed pour non-superadmin.
2. **Service account par tenant** provisionné par signal.
3. **Séquencement gros chantiers IAM** : refonte notifs d'abord, self-service user management ensuite.

## Décisions doctrine architecture marketplace B2B2C (6-7 sept 2026)

**Le chantier le plus structurant du projet** (série iam-platform-credentials + USR-1 à USR-4).

1. **TOUPAC est un marketplace B2B2C, pas juste SaaS multi-tenant.** Le CLIENT bascule sur `tenant=None`.
2. **Deux types d'intégrations API distinctes** : `ApiCredential` (tenant) et `PlatformCredential` (plateforme).
3. **Le chatbot Toupac BI est disponible pour tous les tenants dès création** (retrait `TenantSubscription`).
4. **Acting user via `X-Acting-User-Email`** — `request.user` = CLIENT résolu, pas platform-bot.
5. **Auth CLIENT OTP-only** (email OU phone, Redis, hash SHA256, TTL 5 min).
6. **Trois rôles CLIENT distincts, non fusionnés** (voyageur, commanditaire colis, payeur).
7. **Endpoints CLIENT-scoped cross-tenant** (`/api/v1/customer/*`) accessibles JWT direct OU plateforme + acting user + scope.
8. **Écriture métier ouverte via `platform:*:write`** (deux conditions cumulatives : scope + acting user).
9. **Double throttle** sur endpoints CLIENT : `PlatformKeyRateThrottle` + `ActingCustomerRateThrottle`.
10. **Trace audit fine "qui, pour qui, où"** — `PlatformAuditLog(credential, acting_user, tenant_context)` avec `SET_NULL`.
11. **`PlatformCredential.expires_at` optionnel**, `allowed_ips` vide autorisée (arbitrage documenté, cf. DECISIONS.md).
12. **Portail dev split** : `/developers/` (tenant) + `/partners/developers/` (plateforme).
13. **Pas de fusion automatique de comptes** — feature future `POST /customer/add-contact/`.

## Décisions doctrine notifications (5-8 sept 2026)

1. **Convention `notif.{domaine}.{evenement}.{version}`** — verrouillée charte TOUPAC ONE.
2. **Push + In-app OBLIGATOIRES** sur tous les événements non-OTP. Email selon cas. SMS/WhatsApp OTP-only.
3. **EventCatalog en code = source unique de vérité** (`notifications/catalog.py`, 37 events).
4. **Service explicite `NotificationService.emit()`, jamais signals Django.**
5. **Une `Notification` = un `recipient_user`.**
6. **`variables_schema` en format Python natif** (pas JSON Schema, pas Pydantic).
7. **Préférences user via `User.notification_preferences` JSONField.** NEVER_OPT_OUT : `otp`, `security`, `critical_ops`.
8. **Confidentialité (N-05) asymétrique par canal** : push+SMS+WhatsApp masqués, in-app+email payload complet.
9. **Fail-log symétrique** : 8 branches d'échec préfixées standardisées.
10. **Idempotence 2 niveaux** : Redis pré-résolution + contrainte DB post-résolution.
11. **Retry différencié par canal** (Push/Email 3 tentatives, SMS/WhatsApp/In-app 0).
12. **`transaction.on_commit()` obligatoire** pour enqueue Celery référençant une entité nouvellement créée.
13. **Factory providers configurable via settings** (`NOTIFICATION_PROVIDERS`). Repli asymétrique : canal absent → console silencieux, chemin invalide → ImportError propagée.
14. **La simulation s'annonce** — préfixes explicites (`[SMS-MOCK]`, `[FAKE-PUSH]`) + `provider` distinct.

## Décisions produit récentes prises pendant cette session (à ne PAS oublier)

**Trois décisions structurantes du 8 sept 2026** :

1. **Endpoint `/ack/` CLIENT — infrastructure gardée, aucun event supplémentaire passé à `requires_ack=True` avant validation design app mobile CLIENT.** Aujourd'hui les 2 seuls events `requires_ack=True` visent chauffeurs et dispatchers, aucun voyageur. L'endpoint est correct et sans emploi CLIENT — délibéré. **Repose la question au démarrage app mobile CLIENT.** 3 candidats identifiés pour V2 : `notif.trip.cancelled.v1`, `notif.parcel.available_for_pickup.v1`, `notif.payment.failed.v1`.

2. **Option A SMS différé tranchée.** Continuer chantier notifs (E1/E2/F), brancher SMS/WhatsApp réels quand la clé API du lead sera disponible (Africa's Talking ou Twilio ou D7Networks). Cadrage de 6 étapes prêt dans DETTES.md section « Notifications — passerelles réelles ». La connexion CLIENT par SMS ne fonctionne pas en attendant — dette explicite tracée.

3. **Stack frontend backoffice — reco Vite+React+TS+Tailwind+shadcn/ui+React Query à valider avec le lead avant Chantier BACKOFFICE-BOOTSTRAP.** Repo séparé `toupac_frontend`. Design inspiration Fleetbase console (pas de Figma). Voir section « Stack et décisions figées » ci-dessus pour le détail complet.

**Une décision d'organisation ticket** : **E1 + E2 fusionnés** en un seul ticket au lieu de deux séparés. Plus cohérent, débrief unique, ~29 resolvers en un bloc. Sonnet 4.5, ~1,5-2 jours.

## Cross-check charte notifications TOUPAC ONE (8 sept 2026)

Lecture intégrale du fichier `Charte_notifications_TOUPAC_ONE.xlsx` (4 feuilles : Charte, Référentiel plateformes, Matrice notifications, Gabarits messages) et comparaison avec notre implémentation.

**Respecté** : décision de canal (règles 1-5), règles N-01, N-02, N-04, N-06, N-08, N-09, confidentialité masques catalog, convention nommage, référentiel 7 plateformes, 37 events.

**Dévié** :
- N-05 : sujet email n'est pas masqué (fix quick win au Ticket F).
- INC-01 : resolver plus large que « ack au déclarant » demandé (fix dans chantier conformité Phase E).

**Non traité** (5 points, tracés dans DETTES.md nouvelle section « Notifications — écarts avec la charte TOUPAC ONE ») :
- N-07 temporisation / agrégation (COL-03, TRJ-03, STK-01, APR-01) — impact spam utilisateur direct, prioritaire dans chantier conformité.
- N-03 langue utilisateur non résolue (`User.language` manque).
- Délais programmés / scheduler (TRJ-01 T-24h, FLT-01 J-30, CMP-01 J-30, CMD-02 T-15min) — Celery beat manquant.
- Ack au déclarant (INC-01, CRM-01).
- MKT-01 plafonnement + non-relance post-conversion. Rate limiting métier (CMD-02, PAY-02, APR-01).

**Deux quick wins intégrés au Ticket F** :
- N-05 masquage sujet email (~30 min).
- Contraintes longueur push validation dans `NotificationTemplate.clean()` (~30 min).

**Chantier conformité charte complète** : ~5-6 jours, tracé Phase E du plan.

## Plan de séquencement complet (validé 8 sept 2026)

**Phase A — Fin refonte notifications (~3-4 jours)**
- Ticket E1 + E2 fusionnés : câblage ~29 resolvers métier (voyage/paiement/colis + fleet/incidents/GPS/workflow). Sonnet 4.5, ~1,5-2 j.
- Ticket F : seed 37 templates système + 2 quick wins conformité charte (masquage subject email + validation longueur push) + retrait `send_notification()` legacy + fusion seeders. Sonnet 4.5, ~1 j.

**Phase B — Débloqueurs mise en prod (~6-7 jours)**
- Self-service user management admins compagnie (~3 jours Opus 4.7 — sécurité, durcissement UserAdmin anti-escalade).
- Endpoints d'écriture CLIENT `POST /customer/reservations/`, `/orders/`, `/payments/` (~3-4 jours). Prépare l'app mobile CLIENT.
- **SMS réel dès que la clé du lead arrive** — chantier parallèle, ~1 jour code une fois la clé reçue. Cadrage 6 étapes dans DETTES.md.

**Phase C — Backoffice frontend (~13-16 jours)**
Le gros chantier attendu par le lead. Repo séparé `toupac_frontend`.
- Chantier BACKOFFICE-BOOTSTRAP (~4-5 j) : setup projet React+Vite+TS+Tailwind+shadcn/ui + auth complète + layout sidebar + client API DRF typé + 1 page fonctionnelle bout-en-bout (liste Trips).
- Chantier BACKOFFICE-CRUD-CORE (~5-6 j) : Tenants + Users + Vehicles + Drivers + Routes + Trips (avec vue manifeste).
- Chantier BACKOFFICE-CRUD-BUSINESS (~4-5 j) : Reservations + Orders + Payments + Dashboard (4 compteurs + graphique 7j).

**Phase D — Chantiers métier différenciants (~7-10 jours)**
- Intégration **Tramingo GPS** (~3 j) — polling REST + mapping IMEI→Vehicle + events pré-calculés vers notifs GPS-01/02 déjà câblées Phase A.
- Intégration **VROOM** dispatching optimisé colis (~2-3 j) — microservice HTTP, appel depuis Django lors création batch commandes colis.
- Intégration **OSRM** routing + ETA colis (~1-2 j) — auto-hébergé données OSM UEMOA/CEDEAO.
- Intégration **FCM/APNs** push réel (~1 j) — remplace `FakePushProvider`, dépend compte Firebase.

**Phase E — Conformité charte complète (~5-6 jours)**
- N-07 agrégation/coalescing.
- N-03 langue utilisateur.
- Délais programmés / scheduler Celery beat.
- Ack au déclarant.
- MKT-01 plafonnement.
- Rate limiting métier.

**Phase F — Polish avant vraie mise en prod (~4-5 jours)**
- Import Excel client (véhicules, chauffeurs, lignes).
- HTTPS + Caddy dev.
- CI/CD GitHub Actions.
- MFA TOTP admin.
- Webhooks sortants HMAC pour ERP tiers.
- Metabase branché reporting.

**Bilan global** : ~50-60 jours de travail après cette bascule chat. Sur cadence 1-2 tickets/jour, **8-12 semaines calendaires** pour TOUPAC prod-ready complet avec toutes features différenciantes. Réaliste sur période de contrat.

## État du sprint applicatif au 8 sept 2026

**Ce qui est fait (base historique)** :
- Feature `session_id` batch offline
- QR billets RS256 + endpoint public `/qr-public-key/`
- Tests critiques : auth, multi-tenant isolation, workflow, paiement mocké
- Seed démo 2 tenants (Sahel Express, Dem Dikk)
- Access token denylist Redis
- Fondations API publique : 15 scopes tenant + 10 scopes plateforme

**Livré dans la série iam-admin (3-5 sept 2026)** — génération clé API, démo-ready, service accounts.

**Livré dans la série notifications warm-up + A + A' (5-6 sept 2026, 191 tests)** — canaux enrichis, EventCatalog 37 events, Resolvers, `User.notification_preferences`.

**Livré dans le chantier CLIENT global (6-7 sept 2026, 476 tests, +208)** — iam-platform-credentials, USR-1 à USR-4 (architecture marketplace B2B2C posée).

**Livré dans la fin refonte notifications (7-8 sept 2026, 637 tests, +161)** :
- **Ticket B** : `NotificationService.emit()` refondu, flow 7 étapes, fail-log symétrique 6 branches (puis 8), idempotence 2 niveaux Redis+DB, retry par canal, confidentialité asymétrique. 3 régressions critiques désamorcées (`title_template=""` NOT NULL, fuite cross-tenant `order_by("-tenant_id")` NULLS FIRST, race Celery eager sur FK via `transaction.on_commit()`). +90 tests.
- **Correctif ConsoleProvider post-B** : masquage body hors DEBUG (incident actif prod détecté, pas dette future). +5 tests.
- **Ticket C** : factory providers configurable via `settings.NOTIFICATION_PROVIDERS`, 4 providers (FakePush, EmailSmtp, SmsConsole, WhatsAppConsole), `loggable_body()` partagé, préfixes explicites. +34 tests.
- **Ticket D** : 5 endpoints CLIENT centre d'alertes (list paginée, unread-count, read, ack, mark-all-read). Serializer liste blanche stricte, isolation 404 pas 403, dérivation catalog en lecture / refus en écriture. Bug OpenAPI SerializerMethodField sans annotation corrigé (`spectacular --validate` en routine pre-merge). +47 tests.
- **Cross-check charte notifications TOUPAC ONE (8 sept 2026)** : lecture intégrale du fichier Excel (4 feuilles), rapport respecté/dévié/non traité. 2 quick wins intégrés au Ticket F, 5 écarts tracés dans DETTES.md pour chantier Phase E.

**Ce qui reste immédiatement (Phase A, 1er ticket du nouveau chat)** :
- **Ticket E1+E2 fusionnés** — câblage ~29 resolvers métier. Sonnet 4.5, ~1,5-2 j.
- **Ticket F** — seed 37 templates + 2 quick wins conformité + retrait legacy. Sonnet 4.5, ~1 j.

## Conventions de code établies

**Tests** :
- pytest + pytest-django avec `conftest.py` racine ET `iam/tests/conftest.py` local (fixtures partagées).
- `CELERY_TASK_ALWAYS_EAGER=True` autouse en conftest racine.
- Un package `tests/` par module.
- Utiliser **de vrais JWT** pour tester l'auth (pas `force_authenticate`).
- Tests admin : `Client()` + `client.force_login(user)`, PAS `APIClient`.
- Assertions sur le **contenu**, pas juste le status code.
- Assertions HTML sur UUID/attributs, pas sur labels affichés.
- **Test end-to-end obligatoire** pour toute émission de credential/token.
- **Data migration non triviale = test dédié** via `importlib.import_module`.
- **Tests data-driven sur invariants** — itérer sur `all_events()`, `all_scopes()`.
- **Assertions négatives sur doc publique** : `assert "rotation" not in html`.
- **Compter les queries d'un serializer** (`assertNumQueries`).
- **Tester le double throttle** en abaissant les seuils drastiquement.
- **`spectacular --validate --fail-on-warn`** en routine pre-merge (annoter `SerializerMethodField` avec `-> bool` etc.).

**Ruff** : `select = ["E", "F", "W", "I", "B", "C4", "UP", "RUF"]`, `RUF012` désactivé, `EXE002` non sélectionné, `E402` ignoré sur `config/settings/*.py`, `UP042` actif.

**Répartition 3 fichiers de vérité** :
- **DETTES.md** : dette identifiée à traiter, par domaines.
- **DECISIONS.md** : patterns/anti-patterns validés (~50 entrées, 12 domaines).
- **CONTEXT_TRANSFERT.md** (ce fichier) : état du projet, doctrine produit, décisions structurantes, plan de séquencement.

**Commits** : `feat(scope): ...`, body avec contexte + résultats chiffrés + refs. 1 commit par ticket.

## Fichiers-clés à connaître dans le repo

**Racine** :
- `CONTEXT_TRANSFERT.md`, `DECISIONS.md`, `DETTES.md` — les 3 fichiers de vérité.
- `conftest.py` — fixtures partagées + `CELERY_TASK_ALWAYS_EAGER=True` autouse.
- `docs/design/platform-credentials.md`.

**Config** :
- `config/settings/base.py` — REST_FRAMEWORK, TOUPAC_QR_PRIVATE_KEY_PEM, UNFOLD, **`NOTIFICATION_PROVIDERS`** (Ticket C).
- `config/settings/dev.py` — LOGGING viser `"toupac"` racine (pas `"notifications"`), EMAIL_BACKEND console.
- `config/settings/prod.py` — EMAIL_BACKEND SMTP, vars `EMAIL_*` à remplir en `.env.prod`.

**Core** :
- `core/middleware.py` — TenantMiddleware (slug + UUID).
- `core/models.py` — TenantModel, TenantManager (ne filtre pas), UUIDv7Field, SoftDeleteMixin.
- `core/admin.py` — TenantAdminMixin, SuperadminOnlyAdminMixin.
- `core/management/commands/seed_demo.py` — dataset démo, appelle `seed_notification_templates`.

**IAM** (module massif après chantier CLIENT global) :
- `iam/authentication.py`, `api_key_authentication.py`, `platform_authentication.py` (X-Acting-User-Email).
- `iam/platform_audit.py` — middleware avec `acting_user`.
- `iam/permissions.py`, `platform_scopes.py` (CUSTOMER_SCOPE, platform_scope_for_domain), `scopes.py`.
- `iam/throttles.py`, `platform_throttles.py`.
- `iam/forms.py`, `admin.py`.
- `iam/signals.py`, `guardian.py`.
- `iam/otp.py`, `otp_views.py`.
- `iam/customer_views.py` — CustomerMe, CustomerCompanies, MyReservations/Orders/Payments, **`IsAuthenticatedCustomer` définie ici**.
- `iam/customer_notifications_views.py` — 5 endpoints centre d'alertes (Ticket D).
- `iam/customer_serializers.py` — My* + MyNotificationSerializer.
- `iam/customer_urls.py` — monté sur `/api/v1/customer/`.
- `iam/platform_views.py`, `platform_urls.py`.

**Notifications** :
- `notifications/catalog.py` — 37 events, `all_events()` retourne **list** (pas dict).
- `notifications/priorities.py`, `channels.py`, `preferences.py`.
- `notifications/resolvers/base.py`, `examples.py` — 2 exemples testés + `KNOWN_UNIMPLEMENTED_RESOLVERS` (~29 clés à câbler Phase A).
- `notifications/models.py` — NotificationTemplate, Notification, NotificationLog (`tenant` nullable).
- `notifications/services.py` — `NotificationService.emit()` refondu + adaptateur `send_notification()` legacy avec DeprecationWarning.
- `notifications/tasks.py` — `send_notification_log(log_id)`.
- `notifications/retries.py` — `RETRY_POLICIES` par canal.
- `notifications/rendering.py` — `render_for_channel`, `CHANNELS_MASKING_APPLIED`.
- `notifications/idempotency.py` — helpers Redis.
- `notifications/providers/base.py` — `NotificationProvider` ABC + `NotificationResult` + `loggable_body()` partagé.
- `notifications/providers/factory.py` — `get_provider(channel)`.
- `notifications/providers/console.py`, `fake_push.py`, `email_smtp.py`, `sms_console.py`, `whatsapp_console.py`.

**Voyage / colis / billing** :
- `voyage/models.py` — Passenger avec `customer_user`.
- `voyage/services/qr_jwt.py`.
- `colis/models.py` — Order avec `customer`.
- `billing/models.py` — Invoice avec `customer_type="client_user"`.

**Developers** :
- `developers/views.py`, `urls.py`, `partner_urls.py`.
- Templates `tenant_portal.html`, `partner_portal.html`.

## Anti-patterns

**Source de vérité : `DECISIONS.md` à la racine — ~50 entrées, 12 domaines.**

12 domaines couverts : Idempotence & async, Services et flow, ORM PostgreSQL, Tests, Acting user & B2B2C, Portails & doc publique, Multi-tenant & cross-tenant, Auth secrets & cache, Contraintes DB & cycle de vie modèle, Registries & catalogues, Data migrations, Python/Django, API/auth, Modes de travail.

Extraits critiques :
1. `force_authenticate` avec middleware pré-DRF → vrai JWT.
2. `functools.partial` pour form admin → sous-classe dynamique.
3. `@receiver` sans `dispatch_uid`.
4. `isinstance(x, int)` accepte `bool`.
5. `class X(str, Enum)` → `StrEnum` obligatoire.
6. `RenameField` à la main, jamais interactif.
7. Fail-open sur émetteur indéterminable → refuser.
8. Sentinelle de refus qui survit à son motif → dérivation naturelle.
9. `limit_choices_to` ≠ validation modèle → CheckConstraint.
10. Un middleware résout, il ne refuse pas.
11. Un helper `get_or_create` ne vole pas un identifiant.
12. `unique=True + null=True` > UniqueConstraint partielle sur PostgreSQL.
13. `.distinct()` obligatoire sur `Q(...) | Q(...)` relations.
14. Serializers CLIENT en liste blanche, jamais `__all__`.
15. Contrainte modèle sans auditer tiers post_migrate.
16. `transaction.on_commit()` obligatoire pour enqueue Celery + FK récente.
17. Un provider de dev qui log en clair s'auto-restreint hors DEBUG.
18. La simulation s'annonce (préfixes `[SMS-MOCK]`, `fake_fcm_`).
19. Un défaut vaut pour l'omission, pas pour la déclaration fautive.
20. 404 (jamais 403) sur ressource nominative.
21. Une valeur hors bornes se refuse, elle ne se rabote pas.
22. Test de liste blanche par égalité, pas inclusion.
23. Dériver du catalogue avec repli neutre à la lecture / refus à l'écriture.
24. `spectacular --validate` en routine pre-merge.

## Modes de travail établis

- Je génère des **prompts Claude Code** exhaustifs (fichier par fichier, critères, anti-critères, commit prêt).
- Sonnet 4.5 pour tickets bien cadrés. **Opus 4.7** pour tickets à décisions produit multiples ou refactos exploratoires. Chantier CLIENT global était Opus 4.7 — justifié.
- Le dev revient avec **débrief structuré** : critères passés/échoués, écarts justifiés, bugs découverts, points à trancher.
- **Warm-up avant gros ticket** — lève les angles morts.
- **Faits présumés en tête de prompt** — 5-10 signatures validées ligne par ligne au débrief. Attrape les erreurs de lecture (4+ par ticket en moyenne, tous rattrapés avant code).
- **« N tests minimum » ≠ exactement N**. Le dev complète où il voit un vide.
- **Alignement doctrine multi-endroits** — lister TOUS les fichiers où la doctrine apparaît.
- **Pas deux versions d'un même diff dans un prompt.**
- **Fail-log symétrique** — couvrir toutes les branches d'échec.
- **Discipline de découpage sur gros chantier** — trace en dette et continue plutôt qu'élargir.
- **Décision produit tranchée avant chantier** — quand la question est produit-critique, stopper et arbitrer.
- **Retirer une garantie sécu = arbitrage documenté**, pas relâchement.
- **Auditer périodiquement DECISIONS.md et DETTES.md** — ce ne sont pas des archives mais des documents vivants. Vécu 2× cette session : entrée « masquage ConsoleProvider prod » classée dette alors qu'incident actif, entrée « logger notifications INFO » qui nommait le mauvais logger. À faire idéalement à la fin de chaque gros chantier (fin refonte notifs = maintenant).

## Ce qui vient dans le nouveau chat

**Prochain ticket : Phase A — Ticket E1+E2 fusionnés (câblage ~29 resolvers métier).** Sonnet 4.5, ~1,5-2 jours.

Le nouveau chat démarre par :

1. **Lecture des 3 fichiers de vérité** (`CONTEXT_TRANSFERT.md`, `DECISIONS.md`, `DETTES.md`).
2. **Lecture du module `notifications/` post-Ticket D** :
   - `catalog.py` — les 37 events, structure `NotifEvent`.
   - `resolvers/base.py` — squelette, `KNOWN_UNIMPLEMENTED_RESOLVERS` (~29 clés à implémenter).
   - `resolvers/examples.py` — 2 exemples testés (pattern à reproduire).
   - `services.py` — `emit()` refondu, comprendre comment il consomme les resolvers.
3. **Confirmation compréhension** avant d'ouvrir le prompt E1+E2.

**Ce que E1+E2 fusionnés doit livrer** :

- Implémenter les ~29 resolvers déclarés dans `KNOWN_UNIMPLEMENTED_RESOLVERS`.
- Chaque resolver reçoit `(context, tenant)` et retourne `list[ResolvedRecipient]`.
- Résolution des destinataires selon la sémantique de chaque event (client de la réservation, chauffeur de la mission, dispatchers du tenant, etc.).
- Retirer chaque clé de `KNOWN_UNIMPLEMENTED_RESOLVERS` au fur et à mesure — validation croisée bidirectionnelle du catalog garantit qu'aucune n'est oubliée.
- Tests : au moins 1 test par resolver (~29 tests min), + tests d'invariants (tous les events ont un resolver enregistré).

**Après E1+E2** : Ticket F (seed 37 templates + 2 quick wins conformité + retrait legacy).

**Après F** : Phase B — self-service user management + endpoints écriture CLIENT + SMS réel dès clé du lead.

**Puis Phase C** : Backoffice frontend en repo séparé — nécessite validation du stack avec le lead avant BACKOFFICE-BOOTSTRAP.

**Rappels utiles pour le nouveau chat** :
- **Architecture marketplace B2B2C posée** (voir section dédiée).
- **Deux types d'intégrations API** : ApiCredential (tenant) et PlatformCredential (plateforme + acting user).
- **637 tests verts, 0 régression**. Chantier notifications à 3 tickets près d'être bouclé.
- **Endpoint `/ack/` CLIENT laissé en veille** — pas d'events supplémentaires à `requires_ack=True` avant validation design app mobile CLIENT.
- **SMS/WhatsApp réels différés** — attente clé API du lead.
- **Stack frontend à valider avec le lead** avant démarrage Chantier BACKOFFICE-BOOTSTRAP.
- **Charte notifications cross-checkée** — 2 quick wins pour Ticket F, 5 écarts tracés Phase E.
- **Auditer DECISIONS.md et DETTES.md** en fin de refonte notifs (bon moment) — ce ne sont pas des archives.

**Phrase de raccrochage à coller après CONTEXT_TRANSFERT.md dans le nouveau chat** :

> On sort d'un chat où on a bouclé la refonte notifs (Tickets B / C / D) et fait le cross-check charte. Prochaine étape : Ticket E1+E2 fusionnés (câblage ~29 resolvers métier). Lis DECISIONS.md et DETTES.md, puis dis-moi ce que tu as compris comme prochaine action, et on démarre.
