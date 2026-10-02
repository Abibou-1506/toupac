# TOUPAC — Transfert de contexte

_Généré le 2 sept 2026 après une longue session de sprint applicatif._
_MàJ 5 sept 2026 après la série iam-admin._
_MàJ 6 sept 2026 après les Tickets notifications warmup / A / A' — 191 tests._
_MàJ 7 sept 2026 après le chantier CLIENT global (iam-platform-credentials + USR-1 à USR-4) — 476 tests, architecture marketplace B2B2C posée._
_MàJ 8 sept 2026 après la refonte notifications complète (Tickets B / C / D) + correctif ConsoleProvider + cross-check charte notifications TOUPAC ONE — 637 tests, plan complet A→F cadré._
_MàJ 1er oct 2026 après clôture complète du chantier notifications (E1E2 + F) + renforcement voyage (hardening, swagger, onboard-sale, stop-timestamps, JWT verdict) + petites corrections (parcel-tenant, billing-customer-type, my-orders-recipient) + audit DECISIONS/DETTES — **902 tests verts, 1 xfailed, 0 régression cumulée sur 12 tickets livrés depuis le 8 sept.** Bascule vers chantier **panel admin django-unfold** (rattrapage T2)._
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

**Panel d'administration — décision 1er oct 2026** :
- **Court terme (rattrapage T2) : django-unfold stylé TOUPAC**. Déjà installé (`iam/unfold.py`), charte visuelle TOUPAC à appliquer, dashboard d'accueil, revue ModelAdmin métier, permissions fines par rôle. ~4-5 jours de travail. Rendu moderne (voir [unfoldadmin.com](https://unfoldadmin.com)), **immédiatement démontrable au lead**.
- **Moyen terme (T3+) : panel React séparé si besoin évolue**. Option gardée en réserve pour quand le volume fonctionnel dépassera ce que django-unfold peut absorber confortablement. Stack qui serait retenue : Vite + React 18 + TypeScript strict + Tailwind + shadcn/ui + TanStack Query v5 + React Hook Form + Zod + React Router v6 + TanStack Table v8 + react-leaflet + Recharts + openapi-typescript-codegen. Repo séparé `toupac_frontend`. **Décision différée** — ne pas ouvrir ce chantier tant que django-unfold suffit.

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

## Décisions produit et techniques (27 sept — 1er oct 2026)

Session de 5 jours après le 8 sept, concentrée sur la clôture notifications + renforcement voyage + démarrage réel des intégrations avec l'app contrôleur.

### Décisions produit

1. **`TenantManager` — option A tranchée (filtrage explicite assumé).** Au lieu d'implanter un filtrage automatique (que le docstring de `TenantModel` promettait mensongèrement), on retire la promesse et on assume que l'isolation est faite par `.filter(tenant=...)` partout. **Chantier `security-postgres-rls` ouvert à moyen terme** — à déclencher avant l'onboarding de la deuxième compagnie payante.

2. **Vente à bord sur trajet partiel : `origin_stop` et `destination_stop` obligatoires.** Un contrôleur qui vend à bord sait toujours où le passager monte et descend. Validation stricte contre les RouteStop de la route du voyage.

3. **Horodatages d'escale : option A (deux event_types dédiés).** `stop_arrive` et `stop_depart` séparés d'`activity_transition`. Prépare l'arrivée du tracking GPS automatique qui émettra les mêmes events sans toucher au statut métier.

4. **Pattern « premier gagne » sur `TripStop.ata`/`atd`.** Un deuxième event n'écrase pas l'horodatage initial. Aligné sur `handle_activity_transition` pour `actual_departure_at`/`actual_arrival_at`. Le `status` du stop, lui, est bien mis à jour à chaque appel.

5. **JWT systématique sur toute `Reservation`.** `handle_onboard_sale` signe désormais le billet à bord et l'expose dans le verdict (`details.qr_code_jwt`). Pas d'asymétrie entre billets en ligne et billets à bord. Économise un refetch REST au moment précis où le réseau est mauvais (vente offline).

6. **`Trip.summary` alimenté à la fermeture de session.** Agrégat de fin de voyage (boarded, no_show, revenue_xof, cash_xof) recalculé en entier à chaque `control/close/`. Pas de signal, écriture dans la vue.

7. **`actual_arrival_at` enfin écrit depuis le batch offline.** Avant : seulement par la vue `control/close/` avec `timezone.now()` (heure sync, pas heure réelle). Maintenant : par `handle_activity_transition` sur `arriving → completed` avec `event.created_at_local` (heure device). Les deux chemins coexistent, le batch gagne par « premier gagne ».

8. **Enrichissement du seed de démo pour cas CLIENT.** 4 clients globaux (dont Fatou Mbaye et Ousmane Traoré enrichis avec réservations, commandes, factures, paiements). `Order.recipient_user` renseigné sur certaines commandes pour tester le cas « colis reçu ». `InvoiceGenerator` corrigé pour écrire `customer_type="client_user"` quand il faut.

9. **`/my-orders/` liste aussi les colis reçus.** Vue étendue `Q(customer=user) | Q(recipient_user=user)` avec `.distinct()`. Champ `role` ajouté au serializer (`"sender"` | `"recipient"` | `"both"`) pour que l'UI puisse distinguer visuellement.

### Décisions méthodologiques (règles pour les prompts futurs)

1. **« Lire ce qui existe avant d'écrire un contrôle qui le duplique »** (DECISIONS.md, section Modes de travail). Deux erreurs sur un même ticket (format `seat_map`, contrainte unique de `Reservation`) ont montré qu'une spec sans lecture préalable produit des angles morts. Règle : lire les contraintes base avant de coder le pré-contrôle, et proposer un test par introspection qui compare les deux ensembles.

2. **« Un helper de test absorbe les nouveaux champs obligatoires »** (DECISIONS.md). Plutôt que d'adapter 20 call sites quand un champ obligatoire est ajouté au code sous test, étendre le helper (`sell()`, `make_order()`) pour qu'il absorbe le défaut raisonnable. Les tests existants restent inchangés, les nouveaux surchargent via `**overrides`.

3. **« Grep les lecteurs avant d'en changer la forme »** (DECISIONS.md). Quand un champ est écrit à un endroit mais lu par plusieurs sites (serializers passthrough, comparaisons littérales, tests qui assertent une valeur), auditer **tous les lecteurs** avant de changer sa forme ou son contrat. Trois tickets ont rencontré cet angle mort (customer_type, seat_map, contrainte unique). Règle intégrée aux prompts : nommer le grep lecteurs comme fait à produire, pas comme formalité.

### Décisions en attente du lead

1. **Workflows dynamiques (point 4 du message au dev RN du 1er oct)**. Le graphe `ALLOWED_TRANSITIONS` est hardcodé dans `transitions.py`. Est-ce voulu (workflow standardisé TOUPAC) ou faut-il le rendre configurable par compagnie (CDC §??) ? Dans le second cas : chantier séparé 2-3 jours.

2. **Démo lead à prévoir avant que seul le panel admin soit visible.** 30 minutes avec le dev RN qui montre un vrai contrôleur qui ouvre une session, scanne un QR, fait une vente à bord, voit le JWT s'afficher. Change radicalement la perception du T2.

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

## Plan de séquencement révisé (1er oct 2026)

**Phase A — LIVRÉE** (notifications refonte complète + voyage renforcé) : E1E2, F, hardening, swagger, parcel-tenant, billing-customer-type, my-orders-recipient, onboard-sale-partial-trips, stop-timestamps, JWT-verdict, premier-gagne. 12 tickets, 902 tests, 0 régression.

**Phase T2-RATTRAPAGE — Panel admin django-unfold (en cours, ~4-5 jours)**
Décision du 1er oct 2026 vu le retard T2 (jalon 30 sept passé) : rattraper le S4 « Installation & configuration système » du plan originel en customisant django-unfold plutôt qu'en construisant un panel React séparé.

Découpage prévu en 4-5 micro-tickets :
- **Ticket 1 — Thème TOUPAC pour django-unfold** (~1 j) : couleurs charte, logo, libellés français, sidebar groupée par domaine métier (Voyages / Colis / Facturation / Utilisateurs / Notifications).
- **Ticket 2 — Dashboard admin TOUPAC** (~1 j) : écran d'accueil `/admin/` avec stats clés (voyages aujourd'hui, commandes en cours, incidents ouverts, CA du mois).
- **Ticket 3 — Revue des ModelAdmin métier** (~1,5 j) : passer sur Trip, Reservation, Order, Driver, Vehicle, Route, etc. Ajouter `list_filter`, `search_fields`, grouper `fieldsets`, masquer champs d'exploitation purs, `readonly_fields` sur horodatages.
- **Ticket 4 — Permissions fines par rôle** (~1-1,5 j) : groupes staff proprement configurés, admin de compagnie ne voit que ses données, agent de guichet limité. Pourrait inclure la dette « self-service user management ».
- **Ticket 5 (optionnel) — Documentation PDF pour le gestionnaire TOUPAC** (~0,5 j) : 5-10 pages des 10 opérations courantes.

**Phase B — Débloqueurs mise en prod (~6-7 jours)**
- Self-service user management admins compagnie (~3 jours Opus 4.7 — sécurité, durcissement UserAdmin anti-escalade). Peut être absorbé en partie par le Ticket 4 du panel admin.
- Endpoints d'écriture CLIENT `POST /customer/reservations/`, `/orders/`, `/payments/` (~3-4 jours). Prépare l'app mobile CLIENT.
- **SMS réel dès que la clé du lead arrive** — chantier parallèle, ~1 jour code une fois la clé reçue. Cadrage 6 étapes dans DETTES.md.

**Phase C — Panel React séparé (reporte T3+, optionnel)**
Anciennement « Phase C Backoffice frontend ». Reportée au moment où django-unfold ne suffira plus. À ouvrir uniquement si le lead ou le volume fonctionnel l'exige. Stack déjà cadrée ci-dessus.

**Phase D — Chantiers métier différenciants (~7-10 jours)**
- Intégration **Tramingo GPS** (~3 j) — polling REST + mapping IMEI→Vehicle + events pré-calculés vers notifs GPS-01/02 déjà câblées Phase A. Utilisera les event_types `stop_arrive`/`stop_depart` livrés au ticket du 1er oct.
- Intégration **VROOM** dispatching optimisé colis (~2-3 j) — microservice HTTP, appel depuis Django lors création batch commandes colis.
- Intégration **OSRM** routing + ETA colis (~1-2 j) — auto-hébergé données OSM UEMOA/CEDEAO.
- Intégration **FCM/APNs** push réel (~1 j) — remplace `FakePushProvider`, dépend compte Firebase.

**Phase E — Conformité charte complète (~5-6 jours)**
- N-07 agrégation/coalescing.
- N-03 langue utilisateur.
- Délais programmés / scheduler Celery beat.
- Ack au déclarant INC-01/CRM-01.
- MKT-01 plafonnement.
- Rate limiting métier.

**Phase F — Polish avant vraie mise en prod (~4-5 jours)**
- Import Excel client (véhicules, chauffeurs, lignes).
- HTTPS + Caddy dev.
- CI/CD GitHub Actions.
- MFA TOTP admin.
- Webhooks sortants HMAC pour ERP tiers.
- Metabase branché reporting.

**Petites corrections traçables à glisser dans n'importe quel ticket** :
- `TenantModel` docstring faux (haute, 10 min).
- Chantier `security-postgres-rls` (moyen terme, 2-3 j).
- `UUIDv7Field` v4 (basse, 15 min rename).
- `/api/v1/voyage/qr-public-key/` crash sans clé (20 min).
- PEM env-var Docker → chemin fichier (15 min).
- `Payment.order` jamais renseigné (basse, 15 min).
- Route ↔ RouteStop sans contrainte cohérence (30 min).
- nginx vs Caddy recette (1h investigation).
- HTTPS sur recette (~1h).
- CI/CD GitHub Actions (~2h).

**Angles morts produit à trancher avec le lead** :
- COL-03 (charte dit « Client », catalogue dit `parcel.recipient`) — 15 min + décision.
- `assignment_id` modèle inexistant — décision modélisation vs retrait.
- 10 rôles de la charte repliés sur ADMIN/AGENT/DISPATCHER — étendre `User.Role` ~2 j.
- Ack déclarant INC-01/CRM-01 — ~0,5 j.
- Workflows dynamiques voyage — décision « standardisé vs configurable » (en attente).

**Passerelles réelles à ouvrir dès clés API disponibles** :
- SMS Africa's Talking (reco) ou Twilio ou D7Networks — ~1 j.
- WhatsApp Business via Twilio ou Meta Cloud API — ~1 j + délais Meta.
- Push FCM/APNs — ~1 j + compte Firebase.

**Bilan global** : ~35-45 jours de travail après cette bascule chat, incluant les 4-5 jours du panel admin immédiat. Sur cadence 1-2 tickets/jour, **6-9 semaines calendaires** pour TOUPAC prod-ready complet. Réaliste sur période de contrat prolongée.

## État du sprint applicatif au 1er oct 2026

**902 tests verts, 1 xfailed documentaire, 0 régression cumulée sur 12 tickets livrés depuis le 8 sept.**

**Base historique** :
- Feature `session_id` batch offline
- QR billets RS256 + endpoint public `/qr-public-key/`
- Tests critiques : auth, multi-tenant isolation, workflow, paiement mocké
- Seed démo 2 tenants (Sahel Express, Dem Dikk)
- Access token denylist Redis
- Fondations API publique : 15 scopes tenant + 10 scopes plateforme

**Série iam-admin (3-5 sept 2026)** — génération clé API, démo-ready, service accounts.

**Série notifications warm-up + A + A' (5-6 sept 2026, 191 tests)** — canaux enrichis, EventCatalog 37 events, Resolvers, `User.notification_preferences`.

**Chantier CLIENT global (6-7 sept 2026, 476 tests, +208)** — iam-platform-credentials, USR-1 à USR-4 (architecture marketplace B2B2C posée).

**Fin refonte notifications (7-8 sept 2026, 637 tests, +161)** :
- Ticket B, Correctif ConsoleProvider post-B, Ticket C, Ticket D, Cross-check charte TOUPAC ONE.

**Clôture notifications + chantier voyage (8 sept — 1er oct 2026, 902 tests, +265)** — 12 tickets :

1. **notifications-refonte-E1E2** (commit `79201c2`) : 29 resolvers métier câblés, `resolver_variables` strict, `Order.recipient_user` ajouté. +123 tests.
2. **seed-no-active-control-session** (commit `4d3e87b`) : seed ne crée plus de sessions ControlSession ouvertes fantaisistes.
3. **voyage-batch-hardening** (commit `8843bfb`) : `rejection_code` stable, détection seat_conflict propre sur onboard_sale (anomaly MODERATE), liste blanche `payment_method`, validation seat_map avec `trip_seat_labels()`, verdict enrichi.
4. **notifications-refonte-F** (commit `8b20534`) : retrait adaptateur `send_notification()`, migration OTP vers `emit()` + `recipient_override`, correction docstring `TenantModel`.
5. **notifications-parcel-tenant-guard** (commit `028e719`) : helper `_order()` filtre sur tenant, 4 tests d'isolation cross-tenant.
6. **voyage-swagger-batch-doc** (commit `fbb82ad`) : `ChoiceField` sur `rejection_code` (28 valeurs), 10 `OpenApiExample` par event_type + 2 verdicts, test paramétré que les exemples passent les handlers réels.
7. **voyage-onboard-sale-partial-trips** (commit `a661abd`) : `origin_stop`/`destination_stop` obligatoires avec 5 validations, 7 nouveaux rejection codes, `actual_arrival_at` sur `arriving→completed`, `Trip.summary` alimenté à la fermeture de session, `TripStopSerializer` expose `is_boarding`/`is_alighting` (prefetch `stops__route_stop` pour éviter N+1).
8. **billing-invoice-customer-type-alignment** (commit `4afe95f`) : `InvoiceGenerator` écrit `"client_user"` + `customer_user_id` quand passenger rattaché, `_seed_invoices` priorise les clients rattachés, `_seed_colis` renseigne `Order.recipient_user`, récap seed enrichi avec section « COMPTES CLIENTS GLOBAUX ».
9. **customer-my-orders-with-recipient** (commit `16ae282`) : `MyOrdersView` filtre `Q(customer=user) | Q(recipient_user=user)` + `.distinct()`, champ `role` dans le serializer.
10. **voyage-stop-timestamps-and-onboard-jwt** (commit `b7a8c7d`) : deux nouveaux event_types `stop_arrive`/`stop_depart` dans `voyage/services/handlers/stops.py`, 2 nouveaux rejection codes, `handle_onboard_sale` signe le JWT via `sign_ticket_jwt(reservation)`.
11. **voyage-stop-timestamps-preserve-first** (commit `0c1336e`) : alignement `handle_stop_arrive`/`handle_stop_depart` sur « premier gagne » (helper `_apply_timestamp` extrait).
12. **voyage-onboard-sale-jwt-in-verdict** (commit `e323c68`) : ajout `qr_code_jwt` au dict retourné par `handle_onboard_sale` + `VERDICT_DETAIL_KEYS["onboard_sale"]`.

**Audit `DECISIONS.md` / `DETTES.md` complété le 30 sept + ajouts 1er oct** :
- `DECISIONS.md` — 5 nouvelles entrées : sévérité d'anomalie empeché/advenu, filtrage explicite assumé + RLS à moyen terme, `internal_id` non global, chaque nouveau `emit()` fournit sa variable de résolution, lire la contrainte base avant pré-contrôle. **3 règles méthodologiques** ajoutées au 1er oct : helper qui absorbe les champs obligatoires, grep les lecteurs avant changement de forme, auditer DECISIONS/DETTES en fin de gros chantier.
- `DETTES.md` — 6 modifications + 3 nouvelles dettes tracées (`TenantModel` promise mismatch, `UUIDv7Field` mal nommé, parcel sans garde tenant, chantier RLS, perf pytest actualisée, `Payment.order` non renseigné, Swagger insuffisant pour payloads polymorphes).

**Message au dev RN mobile envoyé le 1er oct 2026** — couvre les 6 sujets : statut voyage + horodatages, `Trip.summary`, vente à bord trajet partiel, JWT dans verdict, horodatages d'escale (`stop_arrive`/`stop_depart`), diagnostic events invisibles, workflows dynamiques en attente lead. **Réponses définitives au dev**, pas d'options en suspens.

**Reset du seed sur recette effectué le 1er oct** — base propre, Fatou Mbaye 22 réservations + 2 commandes + 2 paiements visibles via l'API client, Ousmane Traoré 13 réservations + 2 commandes dont 1 destinataire. 4 compagnies clients globaux configurés. QR codes régénérés et transmis au dev RN pour tests.

**Ce qui est prêt à démarrer dans le nouveau chat** :
- **Ticket 1 panel admin — Thème TOUPAC pour django-unfold** (~1 j, premier à prompter).
- **Micro-ticket `voyage-stop-timestamps-preserve-first`** déjà livré. **Micro-ticket `voyage-onboard-sale-jwt-in-verdict`** déjà livré.
- **Message au dev RN** envoyé. Prochaine interaction : attendre son retour sur implementation côté app.
- **En attente du lead** : décision workflows dynamiques, clé API SMS, feu vert sur éventuels gros chantiers T3 (endpoints écriture CLIENT, mise en prod cloud SN).

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

**Prochain ticket : T2-RATTRAPAGE — Ticket 1 panel admin : Thème TOUPAC pour django-unfold.** Sonnet 4.5, ~1 jour.

Le nouveau chat démarre par :

1. **Lecture des 3 fichiers de vérité** (`CONTEXT_TRANSFERT.md`, `DECISIONS.md`, `DETTES.md`).
2. **Lecture du module `iam/unfold.py`** et de l'admin existant (`iam/admin.py`) pour comprendre la configuration django-unfold en place.
3. **Reconnaissance visuelle de l'inspiration** : [unfoldadmin.com](https://unfoldadmin.com) + regarder la console Fleetbase comme référence d'UX.
4. **Confirmation compréhension** avant d'ouvrir le prompt Ticket 1.

**Ce que le Ticket 1 doit livrer** :

- Charte visuelle TOUPAC (couleurs, logo, favicon) appliquée via les settings `UNFOLD`.
- Libellés français cohérents partout (`verbose_name` sur les modèles, `verbose_name_plural`).
- Sidebar groupée par domaine métier dans `UNFOLD["SIDEBAR"]["navigation"]` : Voyages / Colis / Facturation / Utilisateurs / Notifications / Opérations / Configuration.
- Préservation stricte de l'existant — aucun admin cassé, les 902 tests restent verts.

**Après Ticket 1** : Ticket 2 (Dashboard admin TOUPAC) — écran d'accueil `/admin/` avec stats clés.

**Rappels utiles pour le nouveau chat** :
- **902 tests verts, 0 régression**. Chantier notifications + voyage bouclés.
- **Message au dev RN mobile envoyé** le 1er oct, couvre les 6 sujets techniques. Attendre son retour d'implémentation.
- **Attente lead** : workflows dynamiques (point 4), clé API SMS, feu vert chantiers T3.
- **Démo lead à prévoir** avant que seul le panel admin soit visible (30 min app contrôleur).
- **Fiches références du seed** : Fatou Mbaye (`fatou.mbaye@example.sn`, 22 réservations + 2 commandes + 2 paiements), Ousmane Traoré (`ousmane.traore@example.sn`, 13 réservations + 2 commandes dont 1 destinataire), Khadija Diallo (`khadija.diallo@example.sn`, nouveau client sans historique), `+221770000103` (client identifié par téléphone). Tous les 4 : `Toupac2026!`.
- **Serveur recette** : `http://18.214.15.206`. Base à jour depuis reset du 1er oct.
- **Clé plateforme recette** : `tpc_platform_6e238ca9.5LDJUN-yNrpNvZqBSVGxoqawmYqtmiCYUbchDB0nP_Q`.
- **Auditer DECISIONS.md et DETTES.md** en fin de T2-RATTRAPAGE (bon moment).

**Phrase de raccrochage à coller après CONTEXT_TRANSFERT.md dans le nouveau chat** :

> On sort d'un chat où on a clôturé le chantier notifications (E1E2 + F) et le chantier voyage (hardening + swagger + onboard-sale-partial + horodatages d'escale + JWT verdict). 902 tests, 0 régression. On bascule maintenant vers le **panel admin django-unfold** pour rattraper le T2 en retard. Lis CONTEXT_TRANSFERT.md en entier, puis DECISIONS.md et DETTES.md, puis dis-moi ce que tu as compris comme prochaine action, et on démarre le Ticket 1 : Thème TOUPAC pour django-unfold.
