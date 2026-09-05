# TOUPAC — Transfert de contexte

_Généré le 2 sept 2026 après une longue session de sprint applicatif._
_Mis à jour le 5 sept 2026 après la série de tickets iam-admin (génération de clé,
démo-ready, service accounts) — 139 tests verts, 0 régression, doctrine `admin:*`
tranchée, modèle service account par tenant en place._
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
filesystem MCP). Les documents d'architecture sont dans `docs/`.

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

10 modules, ~48 modèles au total :

| Module | Responsabilité |
|---|---|
| `core` | Mixins de base (TenantModel, UUIDv7, SoftDelete), TenantMiddleware, TenantManager, TenantAdminMixin (isolation admin + exclusion SERVICE_ACCOUNT des FK dropdowns User) |
| `iam` | Tenant (+ `get_or_create_service_account()`), User (custom AbstractBaseUser, 8 rôles dont `SERVICE_ACCOUNT`), ApiCredential, AuditLog, UserDevice, scopes API, signal `post_save(Tenant)` d'auto-provisioning bot |
| `fleet` | VehicleType, Vehicle, Driver, VehicleDocument, Fleet, FleetVehicle |
| `geo` | Place (tenant nullable pour places publiques), Zone |
| `workflow` | WorkflowDefinition, State, Transition, Hook (configurable en DB) |
| `voyage` | Route, RouteStop, Schedule, SeatMap, Trip, TripStop, Passenger, Reservation, Controller, ControlSession, ControlEvent (batch offline), Anomaly, Incident, CashEntry, PassengerAccessLog, LuggagePolicy |
| `colis` | Order, Parcel, DeliveryTask, ProofOfDelivery |
| `billing` | PriceList, PriceRule, Invoice, InvoiceLine, Payment (Intouch mobile money sandbox) |
| `tracking` | Position (pas TenantModel, BigAutoField pour volumétrie), Geofence, GeofenceEvent, TrackingLink |
| `notifications` | NotificationTemplate (tenant nullable pour templates système), NotificationLog — **à refondre selon charte TOUPAC ONE, prochain gros ticket** |
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
   l'escalade de privilèges. Tracé en `DETTES.md` section "Fonctionnel — À venir".

## État du sprint applicatif au 5 sept 2026

**Ce qui est fait** :
- **139 tests verts**, 0 xfail, 0 finding ruff, 0 issue manage.py check
- Feature `session_id` batch offline (contrat verrouillé avec dev RN)
- QR billets RS256 end-to-end + endpoint public `/qr-public-key/`
- Tests critiques : auth (JWT + denylist), multi-tenant isolation API, workflow transitions, paiement Intouch mocké
- 2 dettes sécu multi-tenant fermées (Payment scoping, activity_transition scoping)
- Fuite admin cross-tenant fermée + 2 bonus (UserDevice, WorkflowState)
- Exposition superadmin dans dropdowns User fermée
- Seed démo réaliste 2 tenants (Sahel Express, Dem Dikk) — commande `seed_demo` idempotente
- Access token denylist Redis (dette Sprint 2 §4.19 fermée)
- TenantMiddleware TRIAL débloqué (dernier xfail)
- **Fondations API publique** : 15 scopes (`voyage:read`, `colis:write`, ..., `admin:*`), fail-closed via permission globale, rate limiting par clé (1000/h ou 10000/h admin), portail `/developers/` statique, extension spectacular pour X-API-Key

**Livré dans la série iam-admin (3-5 sept 2026)** :
- **Génération de clé API depuis Django Admin** — form custom avec multi-select scopes (`CheckboxSelectMultiple`), délégation à `ApiCredential.issue()` via `save_form` override, révélation one-shot du secret dans une page dédiée (session flash, TTL 5 min, purge immédiate au `session.pop`), AuditLog émis à la création sans secret dans `changes`, test end-to-end qui appelle réellement `/api/v1/voyage/routes/` avec la clé émise (attrape les clés qui passent les tests unitaires mais répondent 401 en live).
- **Démo-ready** — 4 permissions `*_apicredential` ajoutées chirurgicalement au groupe staff des compagnies (PAS `"iam"` in bloc, évite le risque de superadmin fantôme via `add_user`). Refus dur `admin:*` pour non-superadmin. `ApiCredential.user` passé à `blank=True` (alignement modèle/behavior — `null=True` existait déjà via `SET_NULL`). Docstring `iam/scopes.py` réécrit ("intégrations internes TOUPAC" au lieu de l'ambigu "SI internes du client (ERP maison)"). Portail `/developers/` aligné sur la même formulation (dette de sync). Nouvelle section `## Fonctionnel — À venir` créée dans `DETTES.md`.
- **Service accounts** — nouveau `User.Role.SERVICE_ACCOUNT` + migration choices. `Tenant.get_or_create_service_account()` (méthode d'instance, idempotente). Signal `@receiver(post_save, sender=Tenant, dispatch_uid="iam.provision_service_account")` dans nouveau `iam/signals.py`, importé via `IamConfig.ready()`. Data migration `0004_backfill_service_accounts.py` (RunPython, forward + reverse noop justifié, testée pour de vrai via `importlib`). Form sans champ `user`. `UserAdmin.get_queryset` masque les bots hors superadmin. `TenantAdminMixin._scoped_related_queryset` exclut SERVICE_ACCOUNT des FK dropdowns User. Ajout paragraphe "Compte de service" dans `_auth.html` du portail dev. `make_password(None)` au lieu de `set_unusable_password()` dans la data migration (le modèle historique via `apps.get_model` n'expose pas les méthodes custom).

**Ce qui reste (Phase 2 immédiate)** :
- **Refonte module notifications selon charte TOUPAC ONE** — matrice 37 événements, convention `notif.{domaine}.{evenement}.{version}`, canaux Push+In-app obligatoires, SMS OTP-only, gabarits avec variables typées, endpoints in-app centre d'alertes, champs `requires_ack` et `action_buttons` pour coordination Dispatcher↔Chauffeur. **Prochain gros ticket, à démarrer par lecture de `Charte_notifications_TOUPAC_ONE.xlsx`.**

**Micro-tickets courts prêts à insérer entre 2 gros tickets** :
- **Route↔RouteStop cohérence** (~30 min) — validation `Route.clean()`
- **/qr-public-key/ warning au lieu de crash** (~20 min)

**Phases suivantes** (dans l'ordre) :
- Phase 2 (suite) : intégration Tramingo (polling REST, mapping IMEI→Vehicle), import Excel client (véhicules, chauffeurs, lignes), enrichissements modèle (colis.ForbiddenGoods, Route.category national/international, grille bagage), ré-alignement seed (marques YUTONG, corridors Mali)
- Phase 3 : self-service user management pour admins de compagnie (durcissement `UserAdmin` anti-escalade, workflow email d'invitation vs password direct — cadrage détaillé dans `DETTES.md`), puis modules métier découverts via Excel (Maintenance, Fidélisation, Contrats Partenaires, Suivi carburant)
- Phase 4 : webhooks sortants HMAC (Surface B ERP), Metabase branché reporting
- Phase 5 : MFA TOTP admin, Import CSV commandes, micro-dettes restantes (Route↔RouteStop, /qr-public-key/ warning)

## Conventions de code établies

**Tests** :
- pytest + pytest-django avec `conftest.py` à la racine (fixtures partagées : `tenant_a`, `tenant_b`, `user_admin_a`, `user_admin_b`, `authenticated_client`, `_isolated_throttle_cache` autouse)
- Un package `tests/` par module avec `test_*.py`
- Utiliser **de vrais JWT** pour tester l'auth (pas `force_authenticate` qui court-circuite TenantMiddleware)
- Tests admin : `Client()` + `client.force_login(user)`, PAS `APIClient`. Helper local `grant_admin_permissions(user)` (permissions par app_label)
- Assertions sur le **contenu**, pas juste le status code (pattern "test qui passe pour la mauvaise raison")
- Assertions HTML sur UUID/attributs, pas sur labels affichés
- **Test end-to-end obligatoire** pour toute émission de credential/token : la clé/token émis doit répondre 200 sur un endpoint représentatif avec le scope idoine. Un test unitaire seul rate les clés orphelines qui passent la validation mais répondent 401 en live.
- **Data migration non triviale = test dédié** qui exécute la vraie fonction via `importlib.import_module` (le nom du module de migration commence par un chiffre, l'import direct est syntaxiquement impossible) + `apps.get_model` + vérification d'idempotence par re-run
- Pattern dette lointaine : `@pytest.mark.xfail(strict=True)` documentaire
- Pattern dette imminente : test ordinaire affirmant le bug + docstring TODO

**Ruff** :
- Config dans `pyproject.toml` avec `select = ["E", "F", "W", "I", "B", "C4", "UP", "RUF"]`
- `RUF012` désactivé (idiome Django/DRF pour attributs de classe)
- `EXE002` non sélectionné (faux positif Windows bind-mount)
- `E402` ignoré sur `config/settings/*.py`

**DETTES.md** :
- Fichier à la racine, mis à jour par le **même commit** qui ferme/ouvre une dette
- Structure : Sécurité, Modèle, Ergonomie / robustesse, Ops, Fonctionnel, **Fonctionnel — À venir** (nouvelle section pour tracer les gros chantiers futurs déjà cadrés), Tests / perf
- Section vide → écrire explicitement `_Aucune dette identifiée à date._`
- Entrée Perf PBKDF2 enrichie : chaque création de clé depuis l'admin y passe désormais aussi (~250 ms/appel). À surveiller lors des onboardings partenaires (10 clés d'un coup).
- Entrée "Fonctionnel — À venir" : self-service user management pour admins de compagnie (prérequis prod, cadrage complet inline dans DETTES.md)

**Commits** :
- Convention `feat(scope): ...`, `fix(scope): ...`, `chore(scope): ...`, `test(scope): ...`, `docs: ...`, `refactor(scope): ...`
- Body avec contexte + résultats chiffrés + refs vers tickets/dettes
- 1 commit par ticket, atomique

## Fichiers-clés à connaître dans le repo

- `config/settings/base.py` — REST_FRAMEWORK config (auth chain, throttles), TOUPAC_QR_PRIVATE_KEY_PEM, UNFOLD.SIDEBAR.navigation (déclarative, pas auto)
- `core/middleware.py` — TenantMiddleware (attache tenant depuis JWT/session/header)
- `core/models.py` — TenantModel, TenantManager, UUIDv7Field, SoftDeleteMixin
- `core/admin.py` — TenantAdminMixin, SuperadminOnlyAdminMixin (le mixin écrase tenant en save_model, ajoute tenant aux readonly hors superadmin, filtre queryset, exclut SERVICE_ACCOUNT des FK User)
- `iam/authentication.py` — DenylistJWTAuthentication (JWT + denylist Redis)
- `iam/api_key_authentication.py` — ApiKeyAuthentication (résout tenant depuis credential, retourne `(credential.user, credential)`)
- `iam/permissions.py` — HasApiScope (permission globale, fail-closed)
- `iam/scopes.py` — dict AVAILABLE_SCOPES, ADMIN_SCOPE, docstring en tête = doctrine `admin:*`
- `iam/throttles.py` — ApiKeyRateThrottle, ApiKeyAdminRateThrottle (mutuellement exclusifs, rate par requête)
- `iam/forms.py` — ApiCredentialCreateForm (multi-select scopes, PAS de champ user, refus admin:* pour non-superadmin, injection request via sous-classe dynamique dans admin)
- `iam/admin.py` — ApiCredentialAdmin (save_form délègue à issue() + AuditLog, response_add pose session flash, reveal_view avec check credential_id + TTL, UserAdmin masque SERVICE_ACCOUNT hors superadmin)
- `iam/signals.py` — `@receiver(post_save, sender=Tenant, dispatch_uid=...)` → provisionne service account
- `iam/apps.py` — IamConfig.ready() importe schema + signals
- `iam/tests/test_admin_api_credential_issue.py` — 13 tests admin (émission, reveal one-shot, doctrine admin:*, isolation)
- `iam/tests/test_service_accounts.py` — 8 tests (auto-provisioning, idempotence, invisibilité, backfill migration)
- `voyage/services/qr_jwt.py` — sign/verify RS256 avec fallback éphémère dev
- `voyage/services/event_processor.py` + `handlers/` — traitement des batchs offline
- `core/management/commands/seed_demo.py` — génération dataset démo, groupe staff avec permissions ciblées `*_apicredential`
- `developers/` — portail dev statique, aligné sur doctrine admin:* + paragraphe "Compte de service"
- `conftest.py` (racine) — fixtures partagées

## Anti-patterns à éviter (leçons apprises)

1. **`force_authenticate` avec middleware pré-DRF** → utiliser un vrai JWT dans header Authorization
2. **RUF100 auto-fix qui mange les commentaires métier** → restaurer en commentaire au-dessus du `except`
3. **PEM multi-lignes en env-var Docker** → passer en volume monté (dette Ops)
4. **PRNG global `random.seed(42)` avec skip conditionnels** → un `random.Random` par namespace
5. **Permissions sensibles en opt-in par ViewSet** → enregistrer globalement, fail-closed par défaut
6. **Résoudre le tenant seulement dans le middleware** → l'authentificateur qui connaît la clé/token le résout aussi
7. **`throttle_classes = [A, B]` en croyant à un fallback** → DRF applique tous, le plus bas gagne. Mutex explicite si besoin.
8. **`SimpleRateThrottle` avec rate/cache à l'import** → override en per-request pour respecter fixtures et changements de settings
9. **Extension DRF (auth, permission, serializer) sans OpenApiExtension** → warnings spectacular explosent silencieusement
10. **Assertions HTML sur labels affichés** → asserter sur UUID/valeur des `<option>` (labels changent, valeurs sont stables)
11. **Test qui passe parce que tout est vide** (queryset vide, chaîne inexistante) → vérifier qu'il y a des données observables du bon côté
12. **`override_settings(REST_FRAMEWORK={...})` remplace tout** → merger avec la config existante ou lister explicitement
13. **`functools.partial` pour injecter du contexte dans un form admin** → Django lit `form_class.base_fields` dans `ModelAdmin.get_fields()`, absent d'un partial → AttributeError au chargement. **Utiliser une sous-classe dynamique** (`type(name, (form_class,), {"_request": request})`) qui préserve `base_fields` par héritage.
14. **Data migration qui appelle `user.set_unusable_password()`** → le modèle historique via `apps.get_model` n'expose PAS les méthodes custom (uniquement les champs). Utiliser `make_password(None)` qui produit `"!" + aléatoire` — même résultat, `has_usable_password() is False`.
15. **`@receiver` sans `dispatch_uid`** → double enregistrement si `ready()` est appelé deux fois, disconnect/reconnect impossible en test. **Toujours passer `dispatch_uid`** (chaîne unique et stable, ex : `"iam.provision_service_account"`).
16. **Fail-open sur émetteur indéterminable** → dans une vérification "l'émetteur est-il autorisé à X", si le contexte émetteur est `None` (form instancié hors admin, script batch, tests…), refuser par défaut. Un contexte inconnu ≠ un pass à travers.
17. **Doctrine sécurité formulée en un seul endroit** → aligner simultanément le docstring backend, le `help_text` du form admin, ET la doc `/developers/`. Sinon dette de sync qui refait surface au moment gênant (le portail dit encore "ERP maison du client" alors que le code dit "TOUPAC interne" — vécu 3 sept 2026).

## Modes de travail établis

- Je génère des **prompts Claude Code** exhaustifs (fichier par fichier, critères d'acceptation, anti-critères, commit prêt)
- Sonnet 4.5 gère très bien même des tickets complexes (refonte modèle + signal + migration + tests) tant que les décisions sont tranchées en amont. Réserver Opus 4.7 aux tickets où **plusieurs décisions produit restent à prendre** ou aux refactos multi-modules exploratoires.
- Le dev revient avec **débrief structuré** : tableau critères passés/échoués, écarts au prompt (chacun justifié), bugs découverts en route, points à trancher
- Je réponds aux débriefs en **valorisant les corrections** (le dev me fait souvent voir des erreurs de ma spec), puis génère le suivant
- **Pattern warm-up avant gros chantier** : caser 1-3 micro-tickets courts sur le module cible avant d'attaquer sa refonte. Révèle les angles morts du contexte (vécu : chatbot × multi-tenant, portée admin:*, sémantique user porteur — tous levés en warm-up avant qu'on ne les cristallise dans du code notifs).
- **Faits présumés en tête du prompt** : lister explicitement les 5-10 signatures/patterns/conventions supposées, avec la mention "à confirmer / infirmer dans le débrief". Le dev valide ligne par ligne dans son retour. Attrape mes erreurs de lecture avant qu'elles n'atteignent le code.
- **"N tests minimum" ≠ "exactement N tests"** : le dev complète naturellement là où il voit un vide de couverture (ex : 8 tests service_accounts au lieu des 4 demandés — invariants de sécurité du bot ajoutés spontanément). Garder ce format.
- **Alignement doctrine multi-endroits** : quand une doctrine sécurité/produit est reformulée, lister systématiquement dans le prompt TOUS les fichiers où elle apparaît (docstring code, help_text form, portail dev, DETTES.md, README, doc externe). Sinon dette de sync inévitable.

## Ce qui vient dans le nouveau chat

Prochain ticket : **refonte notifications selon charte TOUPAC ONE**. Le nouveau
chat démarre par :

1. **Lecture de `Charte_notifications_TOUPAC_ONE.xlsx`** — extraire la matrice
   37 événements × canaux × publics × contraintes, la restituer en tableau
   digeste pour alignement.
2. **Lecture de l'existant `notifications/`** (models, serializers, views, tasks,
   providers, seed_notification_templates, templates) — cadrer l'écart entre
   l'existant et la cible charte.
3. **Vérif `Base_collecte_info_Toupac_Transport_1.xlsx`** — règles Toupac
   spécifiques (canaux préférés, plages horaires, opt-out) qu'on aurait ratées.
4. **Repérer les événements Tramingo** dans `api_v1_8.pdf` (excès vitesse,
   sortie zone, etc.) qui doivent devenir des notifs TOUPAC — pas prioritaire
   pour ce ticket-là mais à intégrer proprement.

**3 questions ouvertes à trancher au démarrage** (déjà posées 2 sept, encore
ouvertes parce que la lecture de la charte est le préalable à toute décision) :

- Faut-il un modèle `NotificationTemplate` enrichi (variables typées, contraintes de longueur, `requires_ack`, `action_buttons`) ou garder le modèle actuel simple ?
- Le dispatcher notif : service explicite `NotificationService.emit()` appelé par le code métier + Celery task par delivery, ou signal Django + handlers découplés ?
- Endpoints in-app : `GET /notifications/` scope quelle app ? Utilisateur uniquement, ou aussi tenant-wide (dispatcher voit tout) via `Notification.recipient_scope` + permission `notifications:view_all` ?

**Décision FCM/APNs** à trancher après lecture de la charte : ce qu'elle impose
exactement sur le canal Push (obligatoire dans quel délai, quels providers, gestion
des `device_tokens` sur `UserDevice`, etc.). Peut significativement changer le scope
du ticket (2 jours de plus si intégration FCM/APNs est incluse).

**Après refonte notifications** : self-service user management pour admins de
compagnie (cf. `DETTES.md` section "Fonctionnel — À venir" pour le cadrage
complet). Prérequis prod avant scale du recrutement TOUPAC.
