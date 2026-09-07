# TOUPAC — DECISIONS

Registre des décisions techniques et patterns transverses validés au fil des
tickets. Complète `DETTES.md` (dette identifiée) et `CONTEXT_TRANSFERT.md`
(état du projet) : ici on documente **pourquoi on code de cette façon**.

Une décision entre ici quand elle a été validée par un ticket, qu'elle a
survécu à son débrief, et qu'on veut qu'un nouveau contributeur (ou une
future session Claude) la retrouve sans avoir à relire tout l'historique.

Ordre : les patterns les plus récents en haut, groupés par domaine.

---

## Acting user & patterns d'intégration B2B2C

### Le principal authentifié n'est pas toujours le porteur du secret
_Validé — Ticket user-model-refactor-4 (7 sept 2026)_

Un service B2B2C — chatbot, SDK, gateway, adaptateur — agit pour son
utilisateur final, pas pour lui-même. `request.user` doit être
l'utilisateur final résolu, pas le porteur du secret d'intégration.

Bénéfices : les vues, les filtres et l'audit parlent alors du bon compte
sans connaître le partenaire. `TenantManager` filtre correctement. Les
endpoints CLIENT-scoped fonctionnent identiquement en JWT direct et via
plateforme. Le porteur technique (platform-bot) ne subsiste que pour ce
qui ne concerne personne (endpoints globaux : `/platform/tenants/`,
`/platform/health/`).

Appliqué via `X-Acting-User-Email` / `X-Acting-User-Phone` résolu par
`PlatformApiKeyAuthentication`. Le CLIENT est créé silencieusement s'il
n'existe pas (`get_or_create_client` USR-1). Retour du tuple `(user,
credential)` à DRF avec le user = CLIENT.

Contre-pattern à éviter : `request.user = platform-bot` + logique métier
qui va chercher le CLIENT dans le body ou un paramètre. Multiplie les
points où l'identité est extraite, casse les patterns DRF standard,
rend l'audit inexploitable.

### Deux compteurs de débit pour deux surfaces d'abus
_Validé — Ticket user-model-refactor-4 (7 sept 2026)_

Un plafond par clé protège la plateforme, pas les individus : une clé à
1000/h peut dépenser toute son enveloppe sur une seule personne. Un
second compteur par CLIENT résolu (via acting user) borne l'extraction
par compte.

Règle : quand deux surfaces d'abus co-existent (partenaire vs individu
final), les deux compteurs coexistent. DRF applique tous les throttles,
le plus contraignant l'emporte sans arbitrage. Aucun code de départage à
écrire.

Appliqué : `PlatformKeyRateThrottle` (1000/h par clé) +
`ActingCustomerRateThrottle` (200/h par CLIENT). Le second ne s'active
que si `request.platform_credential` ET `request.user.role == CLIENT`.

Tester en abaissant les seuils drastiquement (2/h, 1/h) pour ne pas
avoir à générer 200 appels : la mécanique est prouvée, pas la valeur.

### Une trace d'audit doit répondre « qui, pour qui, où »
_Validé — Ticket user-model-refactor-4 (7 sept 2026)_

Un journal qui ne dit pas au nom de qui une action a été faite est
inexploitable en incident. « Le chatbot a lu 50 réservations » ne
répond pas à « les réservations de quels clients ? ».

Règle : trois champs distincts pour trois questions.
- **Qui** : `credential` — quelle intégration.
- **Pour qui** : `acting_user` — au nom de quel compte final.
- **Où** : `tenant_context` — quelle compagnie / périmètre.

**Corollaire technique** : `on_delete=SET_NULL` (pas `CASCADE`) sur
`acting_user`. Effacer un compte ne doit jamais effacer la trace des
accès dont il a fait l'objet — c'est justement à ce moment-là que
la trace devient utile.

Appliqué à `PlatformAuditLog(credential, acting_user, tenant_context)`.

### Retirer une garantie de sécurité est un arbitrage, pas un relâchement
_Validé — Ticket user-model-refactor-4 (7 sept 2026)_

La rotation forcée des clés tous les N jours paraît une bonne hygiène.
En réalité elle oblige à retransmettre le secret à chaque échéance —
canal officiel, canal secours, backup incident… chaque transmission est
une occasion de fuite.

Retirer la rotation forcée supprime plus d'occasions de fuite qu'il n'en
crée, **dans la mesure où** :
- La révocation immédiate reste possible en cas de compromission.
- L'audit log complet permet de détecter la compromission.
- L'allowlist IP borne l'attaquant.
- La rotation manuelle volontaire reste offerte pour ceux qui la veulent.

À documenter comme un raisonnement, pas comme une simplification. Un
auditeur qui lit le code demain doit voir les 4 conditions cumulatives
qui rendent le retrait tenable, pas juste « expires_at nullable pour
souplesse ».

Cohérent avec le modèle GitHub PAT et Stripe API Key qui ont fait ce
choix il y a des années sur le même raisonnement.

### Anti-pattern : sentinelle de refus qui survit à son motif
_Découvert — Ticket user-model-refactor-4 (7 sept 2026)_

Une constante ou une exception codée en dur qui encode « cette classe
d'actions est impossible aujourd'hui » devient un piège silencieux le
jour où l'obstacle disparaît. La restriction survit à son motif dans
une zone morte du code, invisible aux tests unitaires qui la
contournent.

Vécu USR-4 : `HasPlatformScope._required_scope` renvoyait un sentinelle
`_WRITE_REFUSED` pour toute action non-lecture — posé en
iam-platform-credentials quand aucun scope d'écriture n'existait.
USR-4 introduit `platform:voyage:write`, `platform:colis:write`,
`platform:billing:write`. Le sentinelle refusait toutes ces actions
avant même de regarder les scopes. La valeur produit était invisible
aux tests unitaires (les tests de scopes étaient tous verts sur les
scopes de lecture).

Règle : préférer une **dérivation qui échoue naturellement** à une
exception codée en dur. Ex :
- Bon : `platform_scope_for_domain(domain, write=True)` dérive
  `platform:{domain}:write`. Un domaine sans scope d'écriture déclaré
  dérive un nom qui n'est dans aucune clé — refus automatique par
  absence, sans liste d'exceptions à maintenir.
- Mauvais : `if action not in READ_ACTIONS: raise WriteRefused()` —
  survit à son motif.

Un test fige la dérivation (tracking sans write déclaré → refus
automatique), pas la constante.

---

## Portails et documentation publique

### Un portail public se découpe par public, pas par sujet
_Validé — Ticket user-model-refactor-4 (7 sept 2026)_

Réunir deux modes d'intégration (tenant / plateforme) sur une même page
oblige chaque lecteur à ignorer la moitié du texte sans savoir laquelle.
Le développeur d'une compagnie qui cherche sa clé API se demande
pourquoi on lui parle de `X-Tenant-ID`. Le développeur chatbot qui
cherche `X-Acting-User-Email` se demande pourquoi on lui parle d'un
admin de compagnie.

Règle : deux publics distincts = deux pages. Renvoi croisé d'une phrase
en tête de chacune, pas un long paragraphe pédagogique. Le lecteur qui
s'est trompé de page doit voir immédiatement où aller sans lire la
page complète.

Appliqué : `/developers/` (mode tenant, ApiCredential) et
`/partners/developers/` (mode plateforme, PlatformCredential).

### Anti-pattern : une documentation d'API dont les affirmations ne sont pas testées
_Découvert — Ticket user-model-refactor-4 (7 sept 2026)_

Une page de documentation qui affirme des règles (« rotation obligatoire
tous les 90 jours », « compagnies abonnées au service ») devient
fausse dès que le code évolue. La doc mensonge se détecte tard, en
général quand un partenaire externe l'invoque en support (« vous nous
aviez dit que… »).

Règle : chaque affirmation testable d'une page publique mérite un test
qui l'ancre. Deux formes possibles :
- Positive : `assert "X-Tenant-ID" in html` — la page dit bien Y.
- Négative : `assert "rotation" not in html` — la page ne dit plus X.

Les deux formes valent équivalemment ; la seconde est cruciale pour
traquer les affirmations obsolètes qui résistent à l'évolution.

Vécu USR-4 : les partiels `_platform_intro.html` affirmaient rotation à
90 jours et compagnies « abonnées ». Six mois après que ni l'une ni
l'autre n'existent. Sans le test navigateur du débrief, la doc mensongeait
en prod pour l'équipe partenaire.

Corollaire : l'anti-critère « déplacé, pas refait » sur un texte de doc
doit céder devant l'obligation de vérité. Un dev qui refuse une consigne
cosmétique pour ne pas mentir en documentation fait le bon choix.

---

## Multi-tenant et cross-tenant

### `all_objects = models.Manager()` explicite à côté de `objects = TenantManager()`
_Validé — Ticket user-model-refactor-3 (7 sept 2026)_

Dès qu'un modèle expose `objects = TenantManager()` (filtre automatique par
`request.tenant`), lui ajouter en même temps `all_objects = models.Manager()`.
Le coût est de 2 lignes ; le bénéfice est que tout futur endpoint
cross-tenant (CLIENT global, superadmin, rapport agrégé) peut bypasser le
filtre proprement sans monkey-patch ni accès au manager privé
`Model._base_manager`.

Vécu USR-3 : plusieurs modèles métier n'avaient pas `all_objects`, les vues
CLIENT-scoped ont dû l'ajouter au fur et à mesure. Chaîne décaissée :
reprendre chaque modèle concerné, changer sa déclaration, regarder les
tests qui dépendaient du comportement de `objects.all()` par défaut. Faire
en amont au moment de déclarer le manager coute rien.

### `limit_choices_to` != validation modèle
_Confirmé — Ticket user-model-refactor-3 (7 sept 2026)_

`limit_choices_to={"role": "client"}` filtre les dropdowns dans l'admin
Django et le formfield par défaut, mais **ne bloque pas** un
`Passenger.objects.create(customer_user=<staff>)` en Python, `bulk_create`,
ou une manipulation directe via l'ORM.

Règle : `limit_choices_to` = ergonomie du formulaire, `CheckConstraint` DB
= doctrine. Les deux ensemble pour une contrainte structurante ; le seul
`limit_choices_to` pour un simple confort UX qui peut être contourné par
un admin techniquement légitime.

Exemples cohabitants dans le code aujourd'hui :
- `User.tenant × role` : `CheckConstraint` (USR-1) + validation `clean()`.
- `Passenger.customer_user` : `limit_choices_to` + `CheckConstraint` (USR-3).

### Query union sur FK optionnelles : `.distinct()` obligatoire
_Découvert — Ticket user-model-refactor-3 (7 sept 2026)_

Une query du type
`Payment.filter(Q(order__customer=user) | Q(invoice__customer_id=user.id))`
génère un `LEFT JOIN` sur chaque relation dans le `Q()`. Un paiement lié
à la fois à une order ET à une invoice (rare mais légitime en cas de
cash flow complexe) est retourné en double.

Règle : ajouter `.distinct()` en fin de query, ou séparer en 2 querysets
unis via `.union()`. La distinction est de lisibilité : `.distinct()`
garde une seule query SQL mais peut être plus coûteux sur de gros
volumes ; `.union()` est plus explicite mais casse le tri commun.

Vécu USR-3 : `Payment.all_objects.filter(Q(order__customer=user) |
Q(invoice__customer_id=user.id, invoice__customer_type="client_user")).distinct()`.

### Serializers cross-tenant : `tenant_slug` par item, pas globalement
_Validé — Ticket user-model-refactor-3 (7 sept 2026)_

Un endpoint qui retourne des données de plusieurs tenants doit inclure
`tenant_slug` (et souvent `tenant_name`) **sur chaque item** de la
réponse, pas comme métadonnée globale. Le client final (chatbot, app
mobile) doit pouvoir dire pour cette réservation-là chez quelle compagnie
elle a été achetée.

Contre-pattern à éviter : `{"tenants": {...}, "reservations": [...]}`
avec un tenant_id sur chaque réservation qui référence l'entrée globale.
Plus compact en JSON mais impose au client de résoudre la référence,
complique le débug et casse la symétrie item-per-item.

Vécu USR-3 : `MyReservationSerializer`, `MyOrderSerializer`,
`MyPaymentSerializer` incluent tous `tenant_slug` et `tenant_name` par
item, via `source="tenant.slug"`.

### Serializers CLIENT stricts : liste blanche des champs, pas liste noire
_Validé — Ticket user-model-refactor-3 (7 sept 2026)_

Un endpoint CLIENT ne doit pas exposer les champs internes staff
(`created_by`, `boarded_by`, `metadata`, `qr_code_jwt`, `provider_tx_id`,
`provider_response`, `refusal_reason`, `internal_notes`, etc.). Utiliser
`serializers.Serializer` avec la liste explicite des champs à exposer
plutôt que `serializers.ModelSerializer` avec `fields = "__all__"` ou
`exclude = [...]`.

Raisons :
- Ajouter un champ interne sur le modèle (ex : nouveau `metadata`) ne le
  fait pas fuiter automatiquement.
- La liste blanche documente explicitement ce que voit le client.
- Une revue de code détecte immédiatement un champ suspect ajouté.

Appliqué aux 3 serializers CLIENT USR-3.

### Compter les queries d'un serializer avant de déclarer `select_related`
_Validé — Ticket user-model-refactor-3 (7 sept 2026)_

Écrire le serializer d'abord, puis compter les `.get()` implicites via
`django_debug_toolbar` en dev ou via un test qui utilise
`assertNumQueries` autour de la sérialisation. Ajuster `select_related` en
conséquence.

Vécu USR-3 : `MyReservationSerializer` sérialisait
`route.origin_place.name` et `route.destination_place.name` qui généraient
chacune une query N+1. Ajout de
`select_related("trip__route__origin_place", "trip__route__destination_place")`.
Sans le test `test_query_count`, la régression serait passée en revue.

Pattern général : tout endpoint qui liste avec un serializer imbriqué
mérite un test qui borne le nombre de queries. Pas de seuil absolu —
fixer le nombre observé initialement, le test devient un canari des
futurs ajouts silencieux.

---

## Auth, secrets et cache

### Le logger `notifications` doit être en INFO en dev
_Validé — Déploiement USR-2 (7 sept 2026)_

`ConsoleProvider` (l'unique provider actif tant que les vrais canaux ne
sont pas branchés) émet `logger.info(...)` avec le corps rendu du message.
Le `LOGGING` Django par défaut est `WARNING` — le message est envoyé,
tracé en base (`NotificationLog.status=sent`), mais invisible dans les
logs Docker. Un dev qui teste un OTP ou une notif ne voit rien passer et
croit à un bug.

Règle : `config/settings/dev.py` (et tout environnement de développement)
configure un handler `console` sur le logger `notifications` en niveau
`INFO`. Le `NotificationLog.content` reste le référentiel des messages
envoyés (utile pour extraire un OTP par script en cas d'urgence de débug),
mais le logger console est ce qu'un développeur regarde en flux continu.

En prod, `INFO` sur `notifications` reste raisonnable : les vrais
providers (FCM, SMTP, providers SMS) auront leurs propres logs et
métriques. On n'y perd pas de signal en gardant `INFO` global.

### Un secret à usage unique se stocke haché, jamais en clair
_Validé — Ticket user-model-refactor-2 (6 sept 2026)_

Même en cache volatil (Redis, memcached). Le hachage protège contre la
lecture accidentelle d'un dump ou d'une inspection ; ce qui protège contre
le brute-force reste le TTL court et le plafond de tentatives, jamais le
hachage seul. Confusion à éviter : le hash n'est pas une défense en
profondeur équivalente au reste, c'est une hygiène minimale.

Appliqué aux OTP (SHA256 stocké, comparaison via `secrets.compare_digest`
en temps constant).

### Écrire l'échéance absolue dans le payload plutôt que d'interroger le TTL
_Validé — Ticket user-model-refactor-2 (6 sept 2026)_

Le backend `django.core.cache.backends.redis.RedisCache` (stdlib Django 4+)
n'expose pas le TTL d'une clé. Réémettre la valeur avec le TTL plein à
chaque réécriture (par exemple pour incrémenter un compteur d'échec)
prolonge la fenêtre indefiniment — une tentative fausse toutes les 4
minutes rend le code utilisable pour toujours.

Solution : stocker l'échéance absolue (`expires_at` ISO) dans le payload.
La réécriture conserve la fenêtre d'origine ; la vérification peut renvoyer
`expired` sans dépendre de la purge Redis.

**Corollaire ferme** : ne jamais atteindre `cache._cache` ou
`cache.client.get_client()` pour contourner une API absente. Un backend
cache Django est un contrat, pas un client Redis déguisé. Si l'API publique
ne suffit pas, adapter la conception, pas contourner.

### Middleware qui accepte plusieurs formats d'identifiant : essayer le plus permissif en premier
_Validé — Ticket user-model-refactor-2 (6 sept 2026)_

Quand un header ou un paramètre peut porter plusieurs formats (slug OU
UUID, id OU email), essayer d'abord le format le plus permissif (celui qui
ne lève pas d'erreur sur input mal typé). Comparer une chaîne quelconque
à une colonne UUID fait lever PostgreSQL ; tenter le slug d'abord évite
ce chemin.

**Point technique subtil** : `filter()` est paresseux, l'erreur PostgreSQL
s'exécute à l'évaluation. Le try/except doit englober `.first()` ou
l'itération, pas la construction du queryset.

```python
# Correct : slug d'abord (permissif), UUID en fallback
tenant = (
    Tenant.objects.filter(slug=header_value).first()  # évalue ici
    or Tenant.objects.filter(id=header_value).first()  # peut lever ValueError
)
```

### Un middleware résout, il ne refuse pas
_Validé — Ticket user-model-refactor-2 (6 sept 2026)_

Laisser `request.tenant = None` et confier le refus aux permissions garde
une seule chaîne de décision. Un middleware qui bloque une requête parce
qu'il ne peut pas résoudre le tenant fragmente la logique de contrôle
d'accès.

**Corollaire découvert au débrief USR-2** : tout backend d'authentification
qui se déclare autoritaire sur `request.tenant` doit le **réinitialiser à
l'entrée**. Sinon une résolution amont (middleware) survit à son refus.

Exemple vécu : `PlatformApiKeyAuthentication` refusait pour abonnement
manquant, mais l'audit log conservait le `tenant_context` visualisé par le
middleware. Fix : deux lignes qui remettent `request.tenant = None` dès
l'entrée de l'auth, avant tout contrôle.

### Anti-pattern : dupliquer un jeu de données de référence entre deux seeders
_Découvert — Tickets notifications-refonte-A et user-model-refactor-2 (5-6 sept 2026)_

Deux commandes de seed qui créent les mêmes entités (gabarits de
notification, rôles de démo, catégories métier) divergent au premier ajout
unilatéral. Vécu : `seed_demo` et `seed_notification_templates` recopiaient
des gabarits sous des clés légèrement différentes — collision d'unicité
évitée par chance (même `get_or_create`), mais divergence de contenu.

Règle : un seeder est primaire, les autres l'appellent au lieu de recopier.
`seed_demo` délègue désormais à `seed_notification_templates`. À généraliser
à tout jeu de données de référence.

### Les noms de variables d'un gabarit sont un contrat
_Découvert — Ticket user-model-refactor-2 (6 sept 2026)_

Le catalogue déclare les variables autorisées par event (`otp`,
`expires_in_minutes`, `device_label`). Les employer de mémoire ou par
supposition dans un gabarit produit un message aux trous silencieux : le
rendu Django `{{code}}` sur un contexte sans `code` renvoie chaîne vide,
aucune erreur, `manage.py check` reste vert, les tests d'envoi passent.
L'utilisateur reçoit son OTP sans code.

Règle : relire la déclaration `variables_schema` de l'event avant d'écrire
le template ou l'appel au service. `validate_context()` du catalog
attraperait l'omission au niveau contexte, pas au niveau template.

---

## Contraintes DB et cycle de vie modele

### `unique=True + null=True` > UniqueConstraint partielle sur PostgreSQL
_Validé — Ticket user-model-refactor-1 (6 sept 2026)_

PostgreSQL traite deux `NULL` comme distincts dans un index unique par
défaut (`NULLS DISTINCT`). Un champ `EmailField(unique=True, null=True,
blank=True)` donne donc « unique quand renseigné » nativement, sans
contrainte partielle, sans opération de migration supplémentaire.

**Piege spécifique Django** : une `UniqueConstraint` conditionnelle sur
`USERNAME_FIELD` déclenche `auth.W004` (« USERNAME_FIELD is not unique »).
`manage.py check` devient rouge. La vérification exige une unicité
garantie ; une contrainte conditionnelle ne satisfait pas.

Solution simple : `unique=True` au niveau champ + `null=True`. `USERNAME_FIELD`
accepte les valeurs nulles (l'authentification par ce champ ne trouvera pas
le user, ce qui est le comportement attendu si l'utilisateur ne s'auth pas
par cette voie).

### `CheckConstraint` comme support de doctrine produit
_Validé — Ticket user-model-refactor-1 (6 sept 2026)_

Une règle métier structurante (« un client est client de TOUPAC, pas d'une
compagnie ») doit tenir contre tout code oublieux : `bulk_create`,
`update()`, migration de données, SQL direct. La vérifier dans `clean()`
ne suffit pas — `clean()` n'est appelé que par les formulaires.

Règle : `clean()` produit le message lisible pour l'utilisateur, la base
tient la règle via `CheckConstraint`. Les tester séparément (le second en
SQL brut / `bulk_create` qui bypasse `clean()`) prouve que le filet
existe.

Appliqué aux 4 contraintes de cohérence rôle × tenant × email × phone sur
`User`.

### Anti-pattern : contrainte de modèle sans auditer les tiers qui écrivent en base
_Découvert — Ticket user-model-refactor-1 (6 sept 2026)_

`django-guardian` matérialise un utilisateur `AnonymousUser` via un signal
`post_migrate`, avec le rôle par défaut du modèle et sans tenant — exactement
ce que la nouvelle contrainte `user_tenant_matches_role` interdisait.

Séquence : migrations → contrainte posée → `post_migrate` → IntegrityError.
Aurait cassé chaque exécution de pytest sur base neuve, la CI, et tout
nouveau clone. La base de dev déjà peuplée ne l'aurait pas révélé.

Règle : avant d'ajouter une contrainte structurante, lister les paquets
tiers qui écrivent en base via `post_migrate` (`django-guardian`,
`django-axes`, `django-notifications-hq`, etc.) et prévoir une fabrique
qui génère des valeurs conformes.

Appliqué via `iam/guardian.py` — branché par `GUARDIAN_GET_INIT_ANONYMOUS_USER`,
donne le rôle `SERVICE_ACCOUNT` à l'AnonymousUser.

### Anti-pattern : `Model.clean()` qui lève sur un champ absent du formulaire
_Découvert — Ticket user-model-refactor-1 (6 sept 2026)_

Quand un mixin d'admin (`TenantAdminMixin`) retire un champ du formulaire
(non-superadmin ne voit pas `tenant`) et le renseigne dans `save_model`,
`Model.clean()` peut voir l'instance sans le champ, lever une erreur
accrochée à ce champ absent. `ModelForm._post_clean` ne sait pas où
l'accrocher et propage un `ValueError` opaque au lieu d'un message.

Règle : quand un mixin d'admin renseigne un champ dans `save_model`,
poser la valeur **avant validation** (via `get_form` override qui
pré-remplit l'instance).

### Un helper `get_or_create` sur des champs uniques doit refuser de voler un identifiant
_Validé — Ticket user-model-refactor-1 (6 sept 2026)_

Combler un champ vide sur un compte existant est sûr ; écrire une valeur
déjà portée par un autre compte est soit un crash (IntegrityError à la
prochaine save), soit une prise de contrôle d'un compte tiers.

Règle : un helper `get_or_create` qui enrichit un compte existant saute
silencieusement un identifiant déjà pris. Fusionner deux comptes exige
une preuve de propriété qu'un helper ne peut pas établir — c'est le rôle
d'un endpoint dédié avec OTP de confirmation.

Appliqué à `User.get_or_create_client()`.

---

## Registries et catalogues déclaratifs

### Validation à l'import, pas au premier envoi
_Validé — Ticket notifications-refonte-A (5 sept 2026)_

Un catalogue déclaratif (`notifications/catalog.py`, `iam/scopes.py`) valide
ses invariants au moment où `register()` est appelé, pas au premier usage.
Une catégorie inconnue, un type de variable non supporté, un masque
`confidentiality_masks` qui pointe sur une variable non déclarée, une liste
de canaux vide : chacune fait échouer le démarrage du conteneur, pas la
première production d'un event métier.

Corollaire : `ready()` de l'AppConfig importe le catalog. Si le catalog est
cassé, `manage.py check` remonte l'erreur au moment du build Docker.

### Validation croisée bidirectionnelle
_Validé — Ticket notifications-refonte-A (5 sept 2026)_

Toute liste « à implémenter » (`KNOWN_UNIMPLEMENTED_RESOLVERS`,
`KNOWN_UNIMPLEMENTED_HANDLERS`, etc.) est validée dans les deux sens par un
test dédié :

1. Sens direct : aucune clé sauvage — chaque référence dans le catalog est
   soit implémentée soit dans la liste « à venir ».
2. Sens inverse : aucune clé oubliée — une clé qu'on a implémentée mais
   qu'on a oublié de retirer de « à venir » fait échouer le test.

Un one-way check (sens direct seulement) reste vert à perpétuité et laisse
la liste polluée. Les deux sens ensemble forcent le nettoyage à chaque
implémentation.

Généralisation : même pattern entre une **table de mapping de migration**
et le **catalogue cible**. `test_every_canonical_target_is_a_registered_event`
compare `LEGACY_TO_CANONICAL.values()` au catalogue — passe rouge si un
code est renommé dans la migration sans l'être dans le catalog (ou
l'inverse). Renforcé au Ticket A' quand un rename `command.*` → `order.*`
a été validé sans qu'aucun test dédié n'ait été modifié.

### Tests data-driven sur invariants, pas sur données spécifiques
_Validé — Tickets notifications-refonte-A et A' (5-6 sept 2026)_

Un test qui itère sur `all_events()` et vérifie un invariant (nommage en
4 segments, catégorie ∈ ALL_CATEGORIES, masques ↔ variables, SMS/WhatsApp
OTP-only, cross-check resolvers) survit sans modification à toute évolution
du contenu du catalog. Un test qui code en dur `notif.command.confirmed.v1`
casse au premier rename.

Vécu : le Ticket A' a renommé 4 events + une catégorie sans toucher un
seul test. Les 191 tests sont restés verts par construction — les invariants
s'appliquent automatiquement aux codes renommés.

Réserver l'écriture en dur d'un event_code aux tests qui vérifient la
mécanique elle-même (`test_validate_context_missing_required_variable`
sur `notif.payment.confirmed.v1` — code stable et représentatif).

### Registre de données surjectif : arbitrer avant d'écrire l'UPDATE
_Validé — Ticket notifications-refonte-A (5 sept 2026, incident évité en dev)_

Un mapping de normalisation qui envoie deux valeurs héritées différentes
vers une même cible sous contrainte d'unicité **plante en production et
passe en dev vide**. Avant d'écrire un `UPDATE`, `RunPython`, ou tout script
de normalisation :

1. Interroger la base réelle : `SELECT COUNT(*), champ_normalisé FROM t
   GROUP BY champ_normalisé HAVING COUNT(*) > 1`.
2. Décider l'arbitre en amont (le plus récent gagne ? le seeder primaire
   gagne ? suppression du doublon ?).
3. Écrire un script qui rend l'arbitre explicite dans le code, pas dans
   une hypothèse implicite.

Cas vécu : deux seeders de gabarits de notification créaient des lignes
`(tenant=NULL, event_type, channel, language)` qui, après renommage
canonique, tombaient sur la contrainte unique. La migration a arbitré en
faveur du seeder primaire avec suppression du doublon.

---

## Data migrations

### Data migration testable via importlib + apps.get_model
_Validé — Ticket iam-service-accounts (5 sept 2026)_

Une data migration non triviale a un test qui l'exécute réellement, pas un
smoke test manuel :

1. Import du module de migration via `importlib.import_module` (le nom
   commence par un chiffre, l'import direct est syntaxiquement impossible).
2. Appel de la fonction `RunPython` avec `apps.get_model` sur un tenant
   créé signal débranché.
3. Vérification de l'idempotence par re-run.

Pattern applicable à toute data migration qui ne fait pas simultanément
schema change dans le même fichier (voir exception ci-dessous).

### Data migration qui casse le pattern testable
_Découvert — Ticket notifications-refonte-A (5 sept 2026)_

Une data migration qui **supprime une colonne dans le même fichier** rend
le pattern testable inapplicable : le modèle historique nécessaire à
`RunPython` (par `apps.get_model`) ne correspond plus au schéma une fois
la migration passée. `forward()` peut fonctionner en production, mais aucun
`apps.get_model` en test ne peut le rejouer.

Compromis acceptable :
- Test qui couvre la **table de correspondance** (un code canonique mal
  orthographié est attrapé).
- Vérification manuelle sur la base de dev + trace des chiffres avant/après
  dans le débrief.

Ne pas tenter de « corriger » au forceps en splittant en 2 migrations juste
pour rendre testable — la cohérence du refactor prime.

### Une data migration ne rattrape que le passé
_Découvert — Ticket notifications-refonte-A' (6 sept 2026)_

Une data migration de normalisation cible les valeurs qui existaient **au
moment où elle a été appliquée**. Les lignes créées après (par un seeder,
une commande admin, un test) qui utilisent l'ancien vocabulaire ne
repassent jamais dans le pipeline de normalisation — elles restent
orphelines silencieusement.

Vécu en dev : après re-play de la migration 0005 (rename event_type →
event_code), il restait 1 template + 6 logs en `notif.command.confirmed.v1`
en base — ces lignes avaient été écrites par `seed_demo` **entre** le
Ticket A et le Ticket A'. La migration cible les codes legacy
(`reservation_confirmed`), pas les codes déjà canoniques.

Sur une base fraîche (staging/prod, où la migration est jouée une seule
fois avant le premier seed), le problème n'existe pas. C'est un artefact
de dev où on itère entre plusieurs versions du code.

Contre-mesures :
1. **Ne pas re-play une migration data pour la corriger** — écrire une
   nouvelle migration de normalisation, pas rejouer l'ancienne.
2. Documenter dans le débrief de tout ticket qui touche une migration data
   les lignes qui pourraient traîner en dev, et fournir le SQL / shell de
   nettoyage manuel.
3. À terme (Ticket F), fusionner les seeders pour qu'ils produisent
   directement les codes canoniques et ne créent plus de dette latente.

### Rename de champ : jamais via le questionneur interactif
_Validé — Ticket notifications-refonte-A (5 sept 2026)_

`python manage.py makemigrations` propose un `RenameField ? [y/N]` quand
il détecte un champ supprimé + un champ ajouté avec les mêmes types. Deux
raisons de ne jamais laisser Django deviner :

1. En non-interactif (CI, Docker build), le questionneur lève `EOFError`.
2. Un « non » (défaut par appui sur Entrée) produit `RemoveField` +
   `AddField` : la colonne est perdue, les données aussi.

Écrire le `RenameField` à la main dans la migration. Si le champ renommé
est référencé par une contrainte (`unique_together`, `constraints`, index),
retirer et recréer la contrainte dans la même migration.

---

## Python / Django

### `StrEnum` obligatoire, jamais `(str, Enum)`
_Validé — Ticket notifications-refonte-A (5 sept 2026)_

En Python 3.11+, `enum.StrEnum` produit une string sur `str(instance)`.
La construction historique `class X(str, Enum)` produit `"X.MEMBER"` au lieu
de `"member"` — la valeur atterrit telle quelle dans les logs et en base.

Ruff `UP042` le signale. Toute nouvelle enum string-based utilise
`StrEnum`. Les anciennes `(str, Enum)` migrent au fil des tickets qui les
touchent.

### `isinstance(x, int)` accepte `True` et `False`
_Validé — Ticket notifications-refonte-A (5 sept 2026)_

`bool` hérite de `int` en Python. Tout validateur de type numérique doit
exclure `bool` explicitement :

```python
if isinstance(value, bool) or not isinstance(value, int):
    raise ValueError(...)
```

Cas vécu : `validate_context()` du catalog acceptait `amount_xof=True`
comme entier valide avant l'ajout du garde `isinstance(x, bool)`.

### `functools.partial` inutilisable pour form admin dynamique
_Validé — Ticket iam-admin génération clé API (3 sept 2026)_

Django lit `form_class.base_fields` dans `ModelAdmin.get_fields()` — un
`partial(FormClass, request=req)` n'expose pas cet attribut, AttributeError
au chargement de la page.

Utiliser une sous-classe dynamique :
```python
def get_form(self, request, obj=None, **kwargs):
    parent_form = super().get_form(request, obj, **kwargs)
    return type(parent_form.__name__, (parent_form,), {"_request": request})
```

### `set_unusable_password()` inaccessible via `apps.get_model`
_Validé — Ticket iam-service-accounts (5 sept 2026)_

Le modèle historique retourné par `apps.get_model` n'expose que les
champs, pas les méthodes custom de l'`AbstractBaseUser`. Dans une data
migration qui touche à User :

```python
from django.contrib.auth.hashers import make_password
user.password = make_password(None)  # produit "!" + aléatoire
```

Équivalent à `set_unusable_password()`, `has_usable_password() is False`.

### `@receiver` sans `dispatch_uid` : anti-pattern
_Validé — Ticket iam-service-accounts (5 sept 2026)_

`dispatch_uid` (chaîne unique et stable, ex : `"iam.provision_service_account"`)
apporte deux protections :

1. Idempotence de l'import : si `ready()` est appelé deux fois (pytest,
   reload), l'ancien handler est remplacé plutôt que dupliqué.
2. Disconnect/reconnect propre en test.

Sans `dispatch_uid`, `signal.disconnect()` doit fournir une référence exacte
à la fonction — impossible si le handler est décoré ou capturé par closure.

---

## API et authentification

### Doctrine `admin:*` : TOUPAC interne uniquement
_Validé — Ticket iam-admin démo-ready (4 sept 2026)_

Le scope `admin:*` (super-scope, satisfait n'importe quelle vérification)
est réservé aux intégrations internes TOUPAC : outillage superadmin,
adaptateurs Toupac CRM maintenus par TOUPAC, futurs services internes.

Aucun tenant client (compagnie de transport ouest-africaine) n'a de cas
d'usage légitime — les cibles n'ont pas d'ERP maison développé sur-mesure.
Les partenaires externes (chatbot Toupac BI, futures intégrations tierces)
reçoivent des combinaisons de scopes explicites, jamais `admin:*`.

Enforcement : `ApiCredentialCreateForm.clean_scopes()` refuse `admin:*`
pour tout émetteur non-superadmin. Fail-closed quand `_request` est None.
Docstring `iam/scopes.py` et portail `/developers/` alignés sur cette
formulation unique.

### Fail-closed sur émetteur indéterminable
_Validé — Ticket iam-admin démo-ready (4 sept 2026)_

Dans toute vérification « l'émetteur est-il autorisé à X », si le contexte
émetteur est `None` (form instancié hors admin, script batch, tests…),
refuser par défaut. Un contexte inconnu ≠ un pass à travers.

Appliqué à `ApiCredentialCreateForm.clean_scopes()` : `admin:*` refusé si
`self._request is None`.

### Service account par tenant : sémantique de la clé API
_Validé — Ticket iam-service-accounts (5 sept 2026)_

Une clé API n'est pas rattachée à un user humain. Chaque tenant est doté
d'un compte technique (`api-bot@<slug>.internal`, rôle `SERVICE_ACCOUNT`,
password inutilisable) provisionné par signal `post_save(Tenant)`.

Toutes les clés d'un tenant pointent vers ce compte. Le champ `user`
n'existe plus dans le form admin — la sémantique visible côté produit est
« la clé appartient au tenant ». Le compte est invisible dans les listings
User pour les tenant admins (superadmin le voit pour diagnostic), et exclu
des FK dropdowns User partout.

Auto-guérison : si le bot est supprimé,
`Tenant.get_or_create_service_account()` le recrée à l'émission suivante.

### Test end-to-end sur toute émission de credential
_Validé — Ticket iam-admin démo-ready (4 sept 2026), généralisé_

Pour tout ticket qui émet un credential (clé API, token JWT, session
lien), un test doit vérifier que le credential émis **répond 200 sur un
endpoint représentatif avec le scope idoine**. Un test unitaire seul rate
les clés orphelines (user désactivé, tenant supprimé) qui passent la
validation mais répondent 401 en live.

Pattern : après l'émission, `curl -H "X-API-Key: <secret>" /api/v1/...`
en test intégration, ou équivalent DRF `APIClient`.

---

## Multi-tenant

### `TenantAdminMixin` fait le boulot d'isolation
_Validé — Ticket iam-admin génération clé API (3 sept 2026)_

Ne pas dupliquer la logique d'isolation tenant côté admin. `TenantAdminMixin`
(dans `core/admin.py`) fait déjà :
- `save_model` écrase `obj.tenant = request.user.tenant` en création pour
  les non-superadmins (le tenant forgé est ignoré silencieusement).
- `get_readonly_fields` ajoute `tenant` aux readonly hors superadmin.
- `formfield_for_foreignkey` scope le queryset `user` au tenant courant
  (et exclut `SERVICE_ACCOUNT` depuis Ticket service-accounts).

Le comportement « silencieux vs ValidationError » sur un tenant forgé est
tranché : silencieux (par écrasement dans save_model). Ne pas re-débattre
à chaque nouveau ModelAdmin.

---

## Modes de travail

### Warm-up avant gros ticket
_Validé — Série iam-admin et notifications-warmup (3-5 sept 2026)_

Avant un gros chantier sur un module, un warm-up (~30 min) sur ce module
révèle les angles morts du contexte :
- Anti-patterns silencieux (retour `None`, exception avalée).
- Champs ou enums manquants qu'on aurait ajoutés au forceps en refonte.
- Absence de fixtures ou de package tests/.

Vécu : le warm-up notifications a levé (1) `return None` silencieux dans
le service, (2) canal `IN_APP` absent de l'enum, (3) `tests.py` vide.
Ces trois points auraient contaminé le Ticket A.

### Faits présumés en tête de prompt
_Validé — Toute la série iam-admin (3-5 sept 2026)_

Un prompt Sonnet/Opus commence par une section « Faits du code à consommer
tels quels » qui liste 5-10 signatures, patterns, conventions supposés
depuis la lecture. Le dev les valide ligne par ligne dans le débrief.

Attrape les erreurs de lecture avant qu'elles n'atteignent le code. Vécu :
5+ « faits » incorrects sur les 4 tickets iam-admin, tous rattrapés au
débrief sans arriver dans du code livré.

### « N tests minimum » ≠ « exactement N tests »
_Validé — Série iam-admin (3-5 sept 2026)_

Un prompt qui liste `N tests minimum` laisse le dev ajouter des tests
là où il voit un vide de couverture. Vécus : +50 tests sur Ticket A
(191 vs 156 min), +7 sur service-accounts (invariants sécurité du bot).

Garder ce format plutôt que « exactement N tests ».

### Alignement doctrine multi-endroits
_Validé — Ticket iam-admin démo-ready (4 sept 2026)_

Quand une doctrine sécurité/produit est reformulée, lister systématiquement
dans le prompt TOUS les fichiers où elle apparaît : docstring code,
`help_text` form, portail dev, `DETTES.md`, `README`, doc externe.

Vécu : la doctrine `admin:*` a été corrigée dans `iam/scopes.py` mais
oubliée dans `developers/templates/.../_scopes.html`. Résultat : dette de
sync découverte en test navigateur post-déploiement, obligation d'un
commit correctif séparé.

### Pas deux versions d'un même diff dans un prompt
_Validé — Ticket notifications-warmup (5 sept 2026)_

Un prompt qui contient un mini-snippet ET un bloc « ordre suggéré » qui
divergent (par exemple ajout d'un champ avec deux labels différents) crée
un flou. Le dev peut passer sans le remonter.

Soit un bloc unique, soit une section « choix A ou B, ma pref X » explicite.

### Fail-log symétrique : lister toutes les branches d'échec
_Découvert — Ticket notifications-warmup (5 sept 2026)_

Un mécanisme de traçabilité d'erreur doit couvrir **toutes** les branches
d'échec possibles, pas seulement celle qui a motivé le ticket. Lister les
scénarios en début de design :
- Ressource absente (template manquant, resolver inconnu).
- Ressource présente mais cassée (template Django syntax error, resolver
  qui lève).
- Ressource présente mais inapplicable (préférences user opt-out,
  destinataire injoignable).

Vécu : le warm-up a couvert « template absent » (log status=failed) mais
oublié « template présent cassé » (task Celery avale l'exception et
meurt en silence). Corrigé au Ticket B.
