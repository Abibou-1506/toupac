# TOUPAC — Architecture Document v1.0

## Section 3 — Architecture applicative

### 3.0 Addendum Section 2 : Module Workflow (4 tables)

Le cahier des charges §4.4 décrit des "États Commande" (brouillon → planifiée → assignée → en cours → livrée → échec → annulée) et le Sprint 2 Fleetbase utilisait un `OrderConfig.flow` (JSONB blob de 9 activités avec 14 champs chacune). Les deux approches ont des défauts :

- **Le CdC** liste des statuts sans définir les transitions autorisées ni les side-effects.
- **Fleetbase OrderConfig** stocke tout le workflow dans un seul champ JSONB. Ça marche, mais c'est impossible à requêter (« quels workflows ont un état boarding ? »), impossible à valider au niveau DB, et le format OBJET (§4.9 J5-STATE) avec ses 14 champs obligatoires par activité est fragile.

**Ma recommandation** : un module Workflow relationnel en 4 tables. Le workflow est défini en DB (pas hardcodé), configurable par tenant, avec une séparation nette entre l'**ordre d'affichage** (linéaire, pour le stepper UI) et le **graphe de transitions** (plus flexible, pour l'API).

#### Leçon §4.9 traduite en règles de conception

| Contrainte Fleetbase | Règle TOUPAC |
|---|---|
| "PAS de cycles bidirectionnels → stack overflow" | La table `workflow_transitions` interdit `(A→B) + (B→A)` via contrainte applicative. Le graphe est un DAG (Directed Acyclic Graph) avec une seule exception : la transition vers `cancelled` depuis tout état |
| "Flow linéaire pour l'affichage" | Chaque état a un `display_order` (1, 2, 3...) qui pilote le stepper/progress bar UI. Le graphe de transitions peut sauter des états (ex : `scheduled → cancelled`) sans casser l'affichage |
| "L'activité created DOIT être présente" | Chaque workflow a exactement un état `is_initial = true`. Contrainte UNIQUE partielle |
| "14 champs par activité (color, logic, events, actions, pod_method...)" | Les métadonnées configurables vivent dans un JSONB `config` sur `workflow_states`, pas dans 14 colonnes. Seuls `code`, `label`, `color`, `display_order` sont des colonnes pour la performance des requêtes |

---

#### Schéma du module Workflow

**`workflow_definitions`** — Un workflow par type d'entité et par tenant. Remplace `order_configs`.

| Colonne | Type | Contrainte | Notes |
|---|---|---|---|
| `id` | UUID v7 | PK | |
| `tenant_id` | UUID | FK tenants | NULL = workflow système (template par défaut) |
| `entity_type` | VARCHAR(30) | NOT NULL | trip, order, delivery_task, parcel, incident |
| `name` | VARCHAR(100) | NOT NULL | "Voyage passagers standard", "Livraison express" |
| `description` | TEXT | | |
| `version` | INTEGER | NOT NULL, DEFAULT 1 | Versionné — on crée une nouvelle version au lieu de modifier |
| `is_active` | BOOLEAN | DEFAULT true | Une seule version active par (tenant, entity_type) |
| `is_system` | BOOLEAN | DEFAULT false | true = template fourni par TOUPAC, non supprimable |
| `created_by` | UUID | FK users | |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

Index unique : `(tenant_id, entity_type) WHERE is_active = true` — garantit un seul workflow actif par type et par tenant.

**`workflow_states`** — États/activités au sein d'un workflow.

| Colonne | Type | Contrainte | Notes |
|---|---|---|---|
| `id` | UUID v7 | PK | |
| `workflow_id` | UUID | FK workflow_definitions, NOT NULL | |
| `code` | VARCHAR(30) | NOT NULL | Identifiant machine : `scheduled`, `preparing`, `boarding`, `in_transit`... |
| `label` | VARCHAR(50) | NOT NULL | Label humain : "Préparation embarquement" |
| `color` | VARCHAR(7) | DEFAULT '#6B7280' | Hex pour le stepper UI |
| `display_order` | SMALLINT | NOT NULL | Ordre linéaire dans le stepper (1, 2, 3...) |
| `is_initial` | BOOLEAN | DEFAULT false | Exactement 1 par workflow |
| `is_terminal` | BOOLEAN | DEFAULT false | Peut être multiple (completed, cancelled) |
| `config` | JSONB | DEFAULT '{}' | Métadonnées configurables (remplace les 14 champs Fleetbase) |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

Le champ `config` JSONB supporte les clés suivantes (toutes optionnelles) :

```json
{
  "require_pod": false,
  "pod_method": "signature|photo|qr_scan|otp",
  "auto_transition_after_minutes": null,
  "required_fields": ["driver_id", "vehicle_id"],
  "allowed_roles": ["dispatcher", "controller", "admin"],
  "notifications": [
    {"channel": "sms", "template": "trip_departure_reminder", "to": "passengers"}
  ],
  "webhooks": ["order.status.changed"],
  "ui_instructions": "Le contrôleur scanne les billets"
}
```

Index unique : `(workflow_id, code)`, `(workflow_id, display_order)`.

Contrainte applicative : exactement 1 état avec `is_initial = true` par workflow.

**`workflow_transitions`** — Transitions autorisées entre états. C'est le graphe.

| Colonne | Type | Contrainte | Notes |
|---|---|---|---|
| `id` | UUID v7 | PK | |
| `workflow_id` | UUID | FK workflow_definitions, NOT NULL | |
| `from_state_id` | UUID | FK workflow_states, NOT NULL | |
| `to_state_id` | UUID | FK workflow_states, NOT NULL | |
| `trigger` | VARCHAR(20) | NOT NULL, DEFAULT 'manual' | manual, automatic, on_event, on_condition |
| `event_type` | VARCHAR(50) | | Pour trigger=on_event : quel event déclenche (ex: `first_boarding`, `all_delivered`) |
| `guard` | JSONB | DEFAULT '{}' | Conditions pour autoriser la transition |
| `priority` | SMALLINT | DEFAULT 0 | Si plusieurs transitions possibles, laquelle évaluer en premier |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

Index unique : `(workflow_id, from_state_id, to_state_id)`.

Le champ `guard` supporte :

```json
{
  "all_parcels_status": "delivered",
  "anomalies_critical_resolved": true,
  "min_boarded_percent": 0,
  "require_role": "dispatcher",
  "require_field_not_null": ["driver_id"]
}
```

**`workflow_hooks`** — Side-effects déclenchés lors d'une transition (notifications, champs à mettre à jour, webhooks).

| Colonne | Type | Contrainte | Notes |
|---|---|---|---|
| `id` | UUID v7 | PK | |
| `transition_id` | UUID | FK workflow_transitions, NOT NULL | |
| `hook_type` | VARCHAR(20) | NOT NULL | notify, update_field, webhook, celery_task |
| `config` | JSONB | NOT NULL | Configuration du hook |
| `execution_order` | SMALLINT | DEFAULT 0 | |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

Exemples de `config` par `hook_type` :

```json
// hook_type = "notify"
{"channel": "push", "template": "trip_boarding_started", "recipients": "passengers_booked"}

// hook_type = "update_field"  
{"field": "actual_departure_at", "value": "NOW()"}

// hook_type = "webhook"
{"event": "trip.status.changed", "include_payload": true}

// hook_type = "celery_task"
{"task": "voyage.tasks.generate_manifest_pdf", "kwargs": {"trip_id": "$entity.id"}}
```

---

#### Workflows système pré-seedés

TOUPAC fournit des workflows par défaut (is_system=true, tenant_id=NULL) que chaque tenant hérite automatiquement. Un tenant peut les cloner et les personnaliser.

**Workflow "Voyage passagers" (entity_type=trip)** — Port direct du flow Sprint 2 :

```
[1] scheduled → [2] preparing → [3] boarding → [4] in_transit 
    → [5] at_stop → [6] arriving → [7] completed
                                               ↗
    (tout état) ─────────────────→ [8] cancelled
```

| display_order | code | label | is_initial | is_terminal | Transition déclencheur |
|:---:|---|---|:---:|:---:|---|
| 1 | `scheduled` | Programmé | ✅ | | Création du trip |
| 2 | `preparing` | Préparation | | | `control/open` (contrôleur ouvre session) |
| 3 | `boarding` | Embarquement | | | Premier `reservation.board` |
| 4 | `in_transit` | En route | | | Départ (contrôleur ou auto) |
| 5 | `at_stop` | À l'escale | | | Arrivée à un `trip_stop` |
| 6 | `arriving` | Arrivée | | | Dernière escale |
| 7 | `completed` | Terminé | | ✅ | `control/close` |
| 8 | `cancelled` | Annulé | | ✅ | Annulation manuelle |

Transitions : `1→2`, `2→3`, `3→4`, `4→5`, `5→4` (retour en route après escale — seule "boucle" autorisée car `4→5→4` n'est pas bidirectionnel au sens Ember, c'est un cycle entre 2 états non-adjacents dans le display), `5→6`, `6→7`, `1→8`, `2→8`, `3→8`.

**Workflow "Commande colis" (entity_type=order)** :

```
[1] draft → [2] confirmed → [3] dispatched → [4] picked_up 
    → [5] in_transit → [6] delivered
                                    ↗
    (1-5) ──────────→ [7] failed
    (1-3) ──────────→ [8] cancelled
```

| display_order | code | label | is_initial | is_terminal |
|:---:|---|---|:---:|:---:|
| 1 | `draft` | Brouillon | ✅ | |
| 2 | `confirmed` | Confirmée | | |
| 3 | `dispatched` | Dispatchée | | |
| 4 | `picked_up` | Enlevée | | |
| 5 | `in_transit` | En transit | | |
| 6 | `delivered` | Livrée | | ✅ |
| 7 | `failed` | Échouée | | ✅ |
| 8 | `cancelled` | Annulée | | ✅ |

**Workflow "Tâche livraison" (entity_type=delivery_task)** :

```
[1] pending → [2] assigned → [3] accepted → [4] en_route 
    → [5] arrived → [6] completed
                              ↗
    (2-5) ──────→ [7] failed
```

---

#### Comptage mis à jour

| Module | Tables Section 2 | + Workflow | Total |
|---|:---:|:---:|:---:|
| IAM | 5 | — | 5 |
| Flotte | 6 | — | 6 |
| Géographie | 2 | — | 2 |
| Voyage | 14 | — | 14 |
| Colis | 4 | — | 4 |
| Facturation | 5 | — | 5 |
| Tracking | 4 | — | 4 |
| Notifications | 2 | — | 2 |
| **Workflow** | — | **4** | **4** |
| **Total** | **42** | **4** | **46** |

---

### 3.1 Structure du projet Django

```
toupac/
├── config/                    # Projet Django (settings, urls, asgi, wsgi)
│   ├── settings/
│   │   ├── base.py            # Settings communs
│   │   ├── dev.py             # DEBUG=True, SQLite fallback, CORS *
│   │   ├── staging.py
│   │   └── prod.py            # Cloud souverain SN
│   ├── urls.py                # Root URL conf → délègue aux modules
│   ├── asgi.py                # Entrypoint Daphne (WebSocket)
│   ├── wsgi.py                # Entrypoint Gunicorn (HTTP)
│   └── celery.py              # Entrypoint Celery
│
├── core/                      # Module transversal — pas d'API propre
│   ├── models.py              # TenantModel (base), UUIDv7Field, StatusField
│   ├── middleware.py           # TenantMiddleware, RequestIdMiddleware
│   ├── permissions.py         # TenantScopedPermission, RolePermission
│   ├── pagination.py          # StandardPagination (CdC : cohérent avec OpenAPI)
│   ├── exceptions.py          # ToupacAPIException, handler DRF custom
│   ├── mixins.py              # TenantQuerySetMixin, AuditMixin
│   └── utils.py               # generate_internal_id(), qr_jwt_sign()
│
├── iam/                       # Module IAM
│   ├── models.py              # Tenant, User, ApiCredential, AuditLog, UserDevice
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py               # Django Admin + unfold
│   ├── signals.py             # post_save → audit_log
│   ├── backends.py            # JWTAuthentication (simplejwt custom)
│   └── tasks.py               # Celery : purge sessions expirées
│
├── fleet/                     # Module Flotte
│   ├── models.py              # VehicleType, Vehicle, Driver, Fleet, FleetVehicle, VehicleDocument
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── signals.py             # Document expiré → notification
│   └── tasks.py               # Celery : alertes expiration documents
│
├── geo/                       # Module Géographie (GeoDjango)
│   ├── models.py              # Place, Zone (PostGIS)
│   ├── serializers.py         # GeoFeatureSerializer (GeoJSON)
│   ├── views.py
│   ├── urls.py
│   └── admin.py               # Admin avec carte Leaflet (django-leaflet)
│
├── workflow/                  # Module Workflow (machine à états configurable)
│   ├── models.py              # WorkflowDefinition, WorkflowState, WorkflowTransition, WorkflowHook
│   ├── engine.py              # WorkflowEngine — cœur de la machine à états
│   ├── serializers.py
│   ├── views.py               # CRUD workflows (admin tenant)
│   ├── urls.py
│   ├── admin.py               # Admin : éditeur de workflow
│   ├── signals.py             # Post-transition → exécuter les hooks
│   ├── validators.py          # Valide le graphe (pas de cycles, 1 initial, ≥1 terminal)
│   ├── seed.py                # Workflows système par défaut
│   └── tasks.py               # Celery : transitions automatiques (timer-based)
│
├── voyage/                    # Module Voyage passagers
│   ├── models.py              # Route, RouteStop, Schedule, Trip, TripStop, Passenger,
│   │                          # Reservation, SeatMap, LuggagePolicy, Controller,
│   │                          # ControlSession, ControlEvent, Anomaly, Incident,
│   │                          # CashEntry, PassengerAccessLog
│   ├── serializers.py
│   ├── views.py               # TripViewSet, ReservationViewSet, ControlViewSet...
│   ├── urls.py                # /api/v1/voyage/...
│   ├── admin.py
│   ├── signals.py             # Reservation.boarded → Trip.booked_seats++
│   ├── services.py            # ControlEventProcessor (port des 481 lignes du Sprint 2)
│   ├── qr.py                  # JWT RS256 sign/verify pour QR billets
│   └── tasks.py               # Celery : génération manifeste PDF, rappels départ
│
├── colis/                     # Module Colis / logistique
│   ├── models.py              # Order, Parcel, DeliveryTask, ProofOfDelivery
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── services.py            # DispatchService (appel VROOM), RouteService (appel OSRM)
│   └── tasks.py               # Celery : optimisation tournées VROOM, notifications client
│
├── billing/                   # Module Facturation
│   ├── models.py              # PriceList, PriceRule, Invoice, InvoiceLine, Payment
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── services.py            # PricingEngine, InvoiceGenerator
│   ├── providers/             # Intégrations paiement
│   │   ├── base.py            # PaymentProvider (abstract)
│   │   ├── wave.py
│   │   ├── orange_money.py
│   │   ├── mtn_momo.py
│   │   └── cinetpay.py        # Agrégateur multi-pays
│   └── tasks.py               # Celery : vérification statut paiement, relances
│
├── tracking/                  # Module Tracking GPS
│   ├── models.py              # Position, Geofence, GeofenceEvent, TrackingLink
│   ├── serializers.py
│   ├── views.py               # PositionViewSet (lecture), TrackingLinkView (public)
│   ├── urls.py
│   ├── admin.py
│   ├── consumers.py           # Django Channels WebSocket consumer (positions live)
│   ├── routing.py             # WebSocket routing
│   ├── services.py            # TraccarBridge (sync positions Traccar → PostgreSQL)
│   └── tasks.py               # Celery : géofence check, purge positions anciennes
│
├── notifications/             # Module Notifications
│   ├── models.py              # NotificationTemplate, NotificationLog
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── providers/             # Intégrations notification
│   │   ├── base.py            # NotificationProvider (abstract)
│   │   ├── africastalking.py  # SMS panafricain
│   │   ├── whatsapp.py        # WhatsApp Business API
│   │   ├── firebase.py        # Push (FCM)
│   │   └── smtp.py            # Email
│   └── tasks.py               # Celery : envoi asynchrone, retry avec backoff
│
└── api/                       # Couche API transversale
    ├── v1/
    │   ├── urls.py             # Agrège tous les modules sous /api/v1/
    │   └── throttling.py       # Rate limiting par tenant et par endpoint
    ├── versioning.py           # URLPathVersioning
    └── docs.py                 # drf-spectacular config (Swagger/OpenAPI auto-généré)
```

#### Convention de nommage Django → PostgreSQL

Django préfixe automatiquement les tables par le nom de l'app : `voyage_trips`, `colis_orders`, `billing_invoices`, etc. Cela évite les collisions et rend les requêtes SQL lisibles sans ambiguïté.

---

### 3.2 Le WorkflowEngine — cœur de la machine à états

Le fichier `workflow/engine.py` est le composant critique. Il remplace à la fois le `OrderConfig.flow` de Fleetbase et le composant Ember `addChildActivities()` qui crashait sur les cycles.

#### Interface publique

```python
class WorkflowEngine:
    """Machine à états configurable, chargée depuis la DB."""

    def get_workflow(self, tenant_id: UUID, entity_type: str) -> WorkflowDefinition:
        """Retourne le workflow actif pour ce tenant et ce type d'entité.
        Fallback sur le workflow système (tenant_id=NULL) si le tenant
        n'a pas de workflow custom."""

    def get_current_state(self, entity) -> WorkflowState:
        """Lit le champ `status` de l'entité et le résout en WorkflowState."""

    def get_available_transitions(self, entity, user) -> list[WorkflowTransition]:
        """Retourne les transitions possibles depuis l'état courant,
        filtrées par les guards (conditions) et le rôle de l'utilisateur."""

    def transition(self, entity, to_state_code: str, user, **context) -> entity:
        """Exécute une transition :
        1. Vérifie que la transition (current → to_state) existe
        2. Évalue les guards
        3. Met à jour entity.status
        4. Exécute les hooks (notifications, update_field, webhook, celery_task)
        5. Crée une entrée dans audit_logs
        Lève WorkflowTransitionError si refusé."""

    def validate_graph(self, workflow_id: UUID) -> list[str]:
        """Vérifie l'intégrité du workflow :
        - Exactement 1 état initial
        - Au moins 1 état terminal
        - Tous les états non-terminaux ont au moins 1 transition sortante
        - Pas de cycles bidirectionnels (A→B et B→A)
        - L'état initial est accessible en display_order=1
        Retourne une liste d'erreurs (vide = valide)."""
```

#### Séquence d'une transition

```
Client (app mobile ou admin)
    │
    ▼
API View (ex: POST /trips/{id}/control/open)
    │
    ├── 1. Charger l'entité (Trip)
    ├── 2. engine.get_current_state(trip) → "scheduled"
    ├── 3. engine.transition(trip, "preparing", user=controller)
    │       │
    │       ├── 3a. Chercher transition (scheduled → preparing) dans workflow
    │       ├── 3b. Évaluer guard: {} → OK
    │       ├── 3c. trip.status = "preparing" ; trip.save()
    │       ├── 3d. Exécuter hooks:
    │       │       ├── update_field: actual_departure_at = NOW()
    │       │       ├── notify: push "Embarquement ouvert" → passengers
    │       │       └── webhook: trip.status.changed → tenant.webhook_url
    │       └── 3e. AuditLog.create(action="transition", changes={"status": ["scheduled","preparing"]})
    │
    └── 4. Retourner la réponse API (trip mis à jour)
```

#### Pourquoi pas django-fsm ?

`django-fsm` est un bon package (états déclarés en décorateurs Python), mais les transitions sont hardcodées dans le modèle. TOUPAC a besoin de workflows **configurables par tenant** : une compagnie de transport interurbain n'a pas les mêmes états qu'un service de livraison express. Stocker les workflows en DB et les évaluer au runtime est la seule approche qui supporte le multi-tenant configurable.

---

### 3.3 State machines par entité

Chaque entité à workflow porte un champ `status VARCHAR(20)` qui est validé par le WorkflowEngine. Le status ne peut changer que via `engine.transition()` — jamais par affectation directe.

#### Trip (voyage passagers)

```
scheduled ──→ preparing ──→ boarding ──→ in_transit ──→ at_stop
                                                         │   ↑
                                                         │   │
    ┌──── cancelled ←── (depuis scheduled,               │   │
    │                    preparing, boarding)        arriving  │
    │                                                  │      │
    │                                                  ▼      │
    │                                            completed    │
    │                                                         │
    └── Le cycle at_stop ↔ in_transit est autorisé ──────────┘
        (escales multiples sur un trajet)
```

Transitions détaillées :

| De | Vers | Trigger | Guard | Hook principal |
|---|---|---|---|---|
| scheduled | preparing | `control/open` | controller assigné | Créer ControlSession |
| preparing | boarding | Premier `reservation.board` | — | — |
| boarding | in_transit | Manuel (contrôleur) | — | `actual_departure_at = NOW()` |
| in_transit | at_stop | Arrivée à un trip_stop | — | `trip_stop.ata = NOW()` |
| at_stop | in_transit | Départ d'une escale | — | `trip_stop.atd = NOW()` |
| at_stop | arriving | Dernière escale | `stop_order == max` | — |
| arriving | completed | `control/close` | Queue events vide, anomalies critiques résolues | Générer résumé, PDF manifeste |
| scheduled | cancelled | Manuel (dispatcher) | — | Notifier passagers |
| preparing | cancelled | Manuel | — | Notifier passagers |
| boarding | cancelled | Manuel (admin seulement) | — | Rembourser billets |

#### Order (commande colis)

```
draft ──→ confirmed ──→ dispatched ──→ picked_up ──→ in_transit ──→ delivered
  │           │              │             │              │
  └───────────┴──────────────┘             └──────────────┘
        → cancelled                           → failed
```

| De | Vers | Trigger | Guard | Hook principal |
|---|---|---|---|---|
| draft | confirmed | Validation client | Champs obligatoires remplis | Notifier dispatcher |
| confirmed | dispatched | VROOM assigne un chauffeur | driver_id, vehicle_id non null | Notifier chauffeur |
| dispatched | picked_up | Chauffeur confirme enlèvement | — | Notifier expéditeur |
| picked_up | in_transit | Automatique | — | Créer tracking_link, notifier destinataire |
| in_transit | delivered | POD capturée | proof_of_delivery exists | Notifier destinataire, générer facture |
| in_transit | failed | Chauffeur déclare échec | — | Notifier dispatcher + expéditeur |
| draft | cancelled | Manuel | — | — |
| confirmed | cancelled | Manuel | — | Notifier expéditeur |
| dispatched | cancelled | Manuel (dispatcher) | — | Notifier chauffeur + expéditeur |

#### DeliveryTask (tâche de livraison)

```
pending ──→ assigned ──→ accepted ──→ en_route ──→ arrived ──→ completed
                │            │           │           │
                └────────────┴───────────┴───────────┘
                                → failed
```

---

### 3.4 Architecture API (DRF)

#### URL namespace

```
/api/v1/
├── auth/                      # iam module
│   ├── login/                 # POST — JWT access + refresh
│   ├── refresh/               # POST — rotation tokens
│   └── logout/                # POST — révocation (denylist jti, §4.19)
│
├── tenants/                   # iam module (super-admin only)
│   └── {id}/
│
├── users/                     # iam module
│   └── me/                    # GET — profil courant
│
├── fleet/
│   ├── vehicle-types/
│   ├── vehicles/
│   │   └── {id}/documents/
│   ├── drivers/
│   └── fleets/
│
├── geo/
│   ├── places/
│   └── zones/
│
├── voyage/                    # Port des 19 endpoints Sprint 2
│   ├── routes/
│   │   └── {id}/stops/
│   ├── schedules/
│   ├── trips/
│   │   ├── {id}/
│   │   ├── {id}/manifest/     # GET — endpoint critique offline
│   │   ├── {id}/stops/
│   │   ├── {id}/control/open/ # POST
│   │   └── {id}/control/close/# POST
│   ├── reservations/
│   │   ├── {id}/board/        # POST
│   │   ├── {id}/refuse/       # POST
│   │   └── {id}/special-case/ # POST
│   ├── passengers/
│   │   └── {id}/              # GET (include_id_card → audit RGPD)
│   ├── controllers/
│   ├── control-events/batch/  # POST — endpoint critique offline sync
│   ├── anomalies/
│   ├── incidents/
│   └── uploads/presign/       # POST — URL pré-signée S3
│
├── colis/
│   ├── orders/
│   │   └── {id}/parcels/
│   ├── parcels/
│   │   └── {id}/
│   ├── delivery-tasks/
│   │   └── {id}/pod/          # POST — preuve de livraison
│   └── dispatch/optimize/     # POST — appel VROOM
│
├── billing/
│   ├── price-lists/
│   │   └── {id}/rules/
│   ├── invoices/
│   │   └── {id}/
│   ├── payments/
│   │   ├── initiate/          # POST — lance le paiement mobile money
│   │   └── webhook/           # POST — callback provider (CinetPay, PayDunya)
│   └── pricing/calculate/     # POST — simulation tarif
│
├── tracking/
│   ├── positions/             # GET — historique positions d'un véhicule
│   ├── live/                  # WebSocket (Django Channels)
│   ├── geofences/
│   └── links/                 # GET — suivi public par token
│
├── notifications/
│   ├── templates/
│   └── logs/
│
├── workflows/                 # workflow module
│   ├── definitions/
│   │   └── {id}/
│   │       ├── states/
│   │       └── transitions/
│   └── {entity_type}/{entity_id}/
│       ├── current-state/     # GET
│       └── available-transitions/ # GET
│
└── webhooks/                  # Réception webhooks externes (Traccar, paiement)
```

#### Chaîne de middlewares

```
Request HTTP
    │
    ▼
[1] SecurityMiddleware (Django — HTTPS, HSTS)
    │
[2] CorsMiddleware (django-cors-headers — origines autorisées)
    │
[3] RequestIdMiddleware (core — ajoute X-Request-Id pour le tracing)
    │
[4] TenantMiddleware (core — résout tenant_id depuis le JWT ou la session)
    │     ├── API mobile : tenant_id extrait du JWT claim `tenant_id`
    │     ├── Admin web : tenant_id extrait de la session Django
    │     └── API publique : tenant_id extrait de l'API key
    │
[5] AuthenticationMiddleware (Django + simplejwt)
    │     ├── JWT pour /api/v1/* (sauf auth/login et tracking/links)
    │     └── Session pour /admin/*
    │
[6] JWTDenylistMiddleware (core — vérifie que le jti n'est pas révoqué)
    │     Pattern §4.19 du Sprint 2 : cache Redis, TTL = durée restante
    │
[7] IdempotencyMiddleware (core — sur tous les POST/PUT/PATCH/DELETE)
    │     Header `Idempotency-Key: <uuid v4>` obligatoire
    │     Stocke la réponse en cache Redis (TTL 24h)
    │     Retourne la réponse cachée avec X-Idempotency-Replayed: true
    │
[8] AuditMiddleware (core — log les mutations dans audit_logs)
    │
    ▼
DRF View (ViewSet / APIView)
    │
    ▼
Response
```

#### Throttling par tenant

```python
# api/v1/throttling.py
THROTTLE_RATES = {
    'tenant_burst': '100/minute',    # Par tenant, toutes API
    'tenant_sustained': '5000/hour', # Par tenant, toutes API
    'auth_login': '10/minute',       # Anti brute-force login
    'batch_sync': '20/minute',       # control-events/batch
    'payment_initiate': '30/minute', # Paiement mobile money
}
```

---

### 3.5 Interaction entre modules

Le module Workflow est le liant entre les modules métier. Voici les principaux flux inter-modules :

**Flux 1 — Réservation d'un billet (Voyage + Billing + Notifications)**

```
App client → POST /voyage/reservations/
    │
    ├── voyage: crée Reservation (status=booked)
    ├── billing: PricingEngine.calculate(route, stops, luggage)
    ├── billing: Payment.initiate(provider=wave, amount=15000)
    │     └── [Celery] → CinetPay/PayDunya API
    ├── voyage: qr.sign_ticket_jwt(reservation) → qr_code_jwt
    └── [Celery] notifications: SMS confirmation + billet QR WhatsApp
```

**Flux 2 — Sync offline contrôleur (Voyage + Workflow)**

```
App contrôleur → POST /voyage/control-events/batch
    │
    ├── Pour chaque event (port du ControlEventProcessor Sprint 2):
    │   ├── Idempotence: client_uuid déjà vu? → skip
    │   ├── Dispatch par event_type:
    │   │   ├── reservation_board → workflow.transition(reservation, "boarded")
    │   │   ├── reservation_refuse → workflow.transition(reservation, "refused") + anomalie
    │   │   ├── onboard_sale → create Passenger + Reservation + CashEntry
    │   │   ├── parcel_verify → voyage: marquer colis vérifié
    │   │   ├── anomaly_create → voyage: créer Anomaly
    │   │   └── ...
    │   └── Auto-anomalies: duplicate_scan, seat_conflict, parcel_non_conform
    │
    └── Réponse: verdict par event (accepted/rejected + anomaly éventuelle)
```

**Flux 3 — Dispatch optimisé (Colis + Fleet + Tracking)**

```
Dispatcher → POST /colis/dispatch/optimize
    │
    ├── colis: récupérer commandes confirmées non-dispatchées
    ├── fleet: récupérer véhicules et chauffeurs disponibles
    ├── geo: positions actuelles des véhicules (Traccar)
    ├── [Celery] → VROOM API (optimisation VRP)
    │     └── VROOM consulte OSRM pour les distances/temps
    ├── colis: créer DeliveryTasks avec sequence_order
    ├── workflow: transition orders confirmed → dispatched
    └── [Celery] notifications: push aux chauffeurs assignés
```

**Flux 4 — Paiement mobile money callback (Billing + Voyage/Colis + Notifications)**

```
CinetPay/PayDunya → POST /billing/payments/webhook
    │
    ├── billing: vérifier signature webhook
    ├── billing: Payment.status = success/failed
    ├── Si voyage: Reservation.payment_status = paid
    │   └── workflow.transition(reservation, "checked_in")
    ├── Si colis: Order.payment_status = paid
    │   └── workflow.transition(order, "confirmed")
    └── [Celery] notifications: SMS/WhatsApp confirmation paiement
```
