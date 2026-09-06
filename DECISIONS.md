# TOUPAC — DECISIONS

Registre des décisions techniques et patterns transverses validés au fil des
tickets. Complète `DETTES.md` (dette identifiée) et `CONTEXT_TRANSFERT.md`
(état du projet) : ici on documente **pourquoi on code de cette façon**.

Une décision entre ici quand elle a été validée par un ticket, qu'elle a
survécu à son débrief, et qu'on veut qu'un nouveau contributeur (ou une
future session Claude) la retrouve sans avoir à relire tout l'historique.

Ordre : les patterns les plus récents en haut, groupés par domaine.

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
