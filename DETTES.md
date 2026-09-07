# Dettes techniques — TOUPAC

Dernier update : 3 sept 2026

Ce fichier consolide les dettes techniques identifiées et **délibérément 
non corrigées** pendant les tickets précédents. Chaque entrée porte : 
état actuel, approche de fix, estimation d'effort, référence.

Les dettes sont classées par domaine, pas par priorité. La priorisation 
se fait avec le lead selon le contexte produit.

---

## Sécurité

_Aucune dette sécurité identifiée à date._

---

## Modèle

- [ ] **Route ↔ RouteStop : duplication origine/destination non verrouillée**
      → État : `Route.origin_place`/`destination_place` et 
        `RouteStop(stop_order=0)`/`RouteStop(stop_order=max)` portent la 
        même info sans contrainte de cohérence. Un dev peut créer une 
        Route avec `origin_place=Dakar` et un `RouteStop(0).place=Thiès` 
        sans erreur.
      → Fix : `Route.clean()` qui vérifie la cohérence + appel de 
        `full_clean()` dans les serializers de création/mise à jour. 
        Ou signal `post_save` sur RouteStop.
      → Effort : ~30 min
      → Ref : conversation création seed démo, 2 sept 2026

---

## Ergonomie / robustesse

- [ ] **`/api/v1/voyage/qr-public-key/` crash au lieu de warning si clé absente**
      → État : quand `TOUPAC_QR_PRIVATE_KEY_PEM` est vide et que la 
        fonction de résolution ne trouve rien, `qr_public_key_pem()` 
        lève une exception non catchée → 500 sur l'endpoint. La spec 
        RS256 disait "warning + retour None + 503 côté endpoint".
      → Fix : try/except dans `qr_public_key_pem()`, retour `None`, 
        warning fort dans les logs. La view existante gère déjà `None` 
        en 503.
      → Effort : ~20 min
      → Ref : incident déploiement dev 2 sept 2026

---

## Ops

- [ ] **PEM en env-var Docker : basculer sur chemin de fichier monté en volume**
      → État : `TOUPAC_QR_PRIVATE_KEY_PEM` en variable d'environnement 
        multi-lignes, format source de bugs récurrents (déjà vécu au 
        premier déploiement dev).
      → Fix : ajouter `TOUPAC_QR_PRIVATE_KEY_PATH`, prioritaire sur 
        PEM inline. Monter la clé en volume `/etc/toupac/qr_private.pem` 
        avec `chmod 600`. Documenter dans README + `.env.prod.example`.
      → Effort : ~15 min code + 5 min doc
      → Ref : incident déploiement dev 2 sept 2026

- [ ] **nginx vs Caddy sur serveur dev : clarifier lequel proxie quoi**
      → État : sur le serveur dev EC2, un nginx pré-existant répond sur 
        localhost:80 en 301, alors que la doc du projet parle de Caddy. 
        L'IP publique tape bien sur Django via un chemin non clarifié.
      → Fix : à investiguer, potentiellement dette de config plutôt que 
        code. Décider une stack unique proxy (nginx OU Caddy) et 
        l'appliquer proprement.
      → Effort : ~1h investigation + selon décision

- [ ] **HTTPS pas encore actif sur serveur dev**
      → État : `http://` nu, "Non sécurisé" dans le navigateur, 
        potentiellement bloquant pour tests app RN (iOS ATS refuse 
        cleartext par défaut, Android récent aussi).
      → Fix : Let's Encrypt via Caddy (auto) ou certbot + nginx. 
        Domaine à décider (`dev.toupac.sn` ou intermédiaire).
      → Effort : ~1h une fois le domaine choisi

- [ ] **Aucune CI/CD** 
      → État : `.github/workflows/` absent. Chaque push vers `main` 
        peut casser sans que rien ne le détecte.
      → Fix : GitHub Actions minimal : `ruff check` + `pytest` + 
        `spectacular --validate` + build Docker sur push et PR.
      → Effort : ~2h

---

## Fonctionnel (CDC neuf, à prioriser avec lead)

- [ ] Import CSV commandes (CDC §4.4) — ~1 jour
- [ ] MFA sur comptes admin (CDC §6.2) — ~1 jour
- [ ] Webhooks externes avec inscription + retry + signature HMAC (CDC §4.12) — 1-2 jours
- [ ] RBAC granulaire via django-guardian (installé mais non exploité) — 2-3 jours
- [ ] Reporting/BI (CDC §4.11) — Metabase branché lecture seule sur PG, ~1 semaine
- [ ] Onboarding chauffeur seedé (CDC §5.3) — reporté V1.5 par décision produit

---

## Fonctionnel — À venir

### Self-service user management pour admins de compagnie

Habilite les admins de compagnie à créer/modifier/désactiver leurs propres 
utilisateurs (dispatchers, agents, contrôleurs, chauffeurs) depuis l'admin 
Django, sans risque d'escalade de privilèges. **Prérequis prod** : sans cette 
capacité, TOUPAC devient goulot d'étranglement à chaque embauche client.

Portée technique :
- Ajouter `add_user`, `change_user`, `view_user` au groupe staff dans 
  `seed_demo.STAFF_GROUP_APPS` (ou via ajout ciblé équivalent au pattern 
  des `*_apicredential`).
- Durcir `UserAdmin` contre l'escalade : restreindre les choix de `role` 
  (jamais `SUPERADMIN`, à trancher pour `ADMIN`), masquer/readonly 
  `is_superuser`, contrôler `is_staff`, restreindre le choix de `groups` 
  aux groupes auxquels l'émetteur appartient déjà, empêcher l'ajout direct 
  de `user_permissions`.
- Choix workflow : mot de passe défini par l'admin vs email d'invitation 
  avec lien de définition. Second plus safe (le password ne transite par 
  personne).

À planifier après la refonte notifications.

### Order.recipient_user — le destinataire n'est pas modélisé

- [ ] **Un client destinataire d'un colis ne le voit pas dans son espace**
      → État : seul le commanditaire est relié (`Order.customer`).
        `/customer/my-orders/` ne retourne donc que les colis qu'on a expédiés,
        jamais ceux qu'on attend. Le destinataire n'existe qu'en texte libre sur
        la tâche de livraison (`recipient_name`, `recipient_phone`).
      → Cas d'usage manquant : Fatou envoie un colis à sa fille Aïcha, qui a un
        compte ; Aïcha ne voit pas son colis arriver.
      → Fix : `Order.recipient_user` facultatif, puis union
        `customer=user | recipient_user=user` dans la vue. Prévoir la
        distinction à l'affichage — « envoyé » et « à recevoir » ne se lisent
        pas pareil.
      → Effort : ~0,5 j
      → Ref : ticket USR-3, 7 sept 2026.

### Endpoints d'écriture pour le client (POST)

- [ ] **Le client ne peut rien créer depuis son espace**
      → État : USR-3 ne livre que de la lecture. Réserver ou expédier passe
        encore par un guichet ou le chatbot.
      → Fix : `POST /customer/reservations/` et `POST /customer/orders/`,
        exigeant `X-Tenant-Id` (le client désigne la compagnie chez qui il
        achète) et posant `Passenger.customer_user = request.user` à la
        création. Attention au cas « je réserve pour un proche » : le formulaire
        doit permettre de ne pas se désigner soi-même comme voyageur.
      → Effort : ~1 j
      → Seuil : démarrage de l'intégration de l'app mobile client.
      → Ref : ticket USR-3, 7 sept 2026.

### Rattacher un second canal à un compte client existant

- [ ] **Un client « e-mail seul » qui se connecte par téléphone crée un doublon**
      → État : `get_or_create_client` résout par e-mail puis par téléphone. Un
        client connu par son e-mail qui demande pour la première fois un code
        sur un numéro jamais associé obtient un **second** compte, avec un
        historique séparé.
      → Pourquoi c'est volontaire : rattacher le numéro au compte existant
        reviendrait à croire sur parole qu'il s'agit de la même personne. Le
        helper refuse déjà de recopier un identifiant déjà porté par un autre
        compte (USR-1) — précisément pour ne pas offrir une prise de contrôle à
        qui devine un numéro.
      → Fix : endpoint `POST /api/v1/customer/add-contact/`, réservé à un
        client déjà connecté, qui envoie un code de confirmation sur le canal à
        ajouter. La preuve de possession est alors établie, la fusion devient
        légitime. Prévoir la fusion des historiques (USR-3 aura posé les FK).
      → Effort : ~1 j
      → Seuil : premiers doublons remontés après la démo lead.
      → Ref : ticket USR-2, 7 sept 2026.

- [ ] **Le code de connexion est stocké en clair dans `NotificationLog.content`**
      → État : le journal d'envoi conserve le message tel qu'il a été livré,
        code compris. **Le Ticket B n'a pas corrigé ce point**, contrairement à
        ce qui était annoncé ici : les `confidentiality_masks` s'appliquent au
        *rendu poussé* vers l'utilisateur, pas à ce que le serveur écrit sur
        lui-même. Les masquer dans `content` reviendrait d'ailleurs à ne plus
        savoir ce qui a réellement été envoyé — ce à quoi ce champ sert.
      → Portée réelle : le code n'est exploitable que 5 minutes, et les lignes
        sans compagnie ne sont visibles que du superadmin (le mixin d'admin
        filtre par tenant). Mais la ligne, elle, est conservée indéfiniment.
      → Fix envisagé : purge courte des `NotificationLog` de catégorie `otp`
        (quelques heures suffisent à diagnostiquer un envoi), plutôt qu'un
        masquage qui viderait le champ de son sens. À traiter avec la rétention
        générale du journal.
      → Effort : ~0,5 j
      → Ref : ticket USR-2, révisé au Ticket B, 7 sept 2026.

- [x] **~~Le provider console écrivait le message complet dans les logs~~** —
      corrigé le 7 sept 2026. `ConsoleProvider` sert partout tant que la
      fabrique par canal n'existe pas (Ticket C), production comprise, et
      `prod.py` journalise `toupac` à INFO : codes de connexion, QR de billets
      et montants partaient en clair dans la sortie standard. Le corps du
      message n'est désormais écrit que sous `DEBUG` ; hors développement,
      seuls le destinataire et la longueur subsistent. Le vrai correctif reste
      le Ticket C, qui remplacera ce provider par de vraies passerelles.

### JS admin — affichage conditionnel du champ tenant selon le rôle

- [ ] **Le formulaire utilisateur propose « Compagnie » pour tous les rôles**
      → État : depuis USR-1, la combinaison rôle/tenant est contrainte (CLIENT et
        SUPERADMIN sans compagnie, rôles opérationnels avec). `User.clean()` et
        les contraintes de base refusent une saisie incohérente, mais
        l'opérateur ne l'apprend qu'à la soumission.
      → Fix : un JS léger qui masque le champ « Compagnie » quand le rôle
        sélectionné est CLIENT ou SUPERADMIN, et le rend obligatoire sinon.
      → Effort : ~1 h
      → Non bloquant : la validation serveur est complète, seul le confort
        manque.
      → Ref : ticket USR-1, 7 sept 2026.

### Deux endpoints listent les mêmes compagnies

- [ ] **`/platform/tenants/` et `/customer/companies/` renvoient le même contenu**
      → État : depuis la suppression des abonnements (USR-4), les deux listent
        les compagnies actives ou en essai. Ils diffèrent seulement par leur
        public — le partenaire pour l'un, le client pour l'autre — et par une
        colonne (`country_code`, absente du premier).
      → Pourquoi c'est resté : les fusionner obligerait un des deux publics à
        appeler un chemin qui ne lui parle pas, ou à conserver un alias. Le
        doublon coûte moins qu'une indirection tant que les deux réponses
        restent identiques.
      → Fix : trancher une URL unique et documenter la seconde comme dépréciée,
        ou assumer la divergence en enrichissant l'une des deux (statut
        d'abonnement, disponibilité par service).
      → Effort : ~2 h
      → Seuil : dès que les deux réponses cessent d'être identiques.
      → Ref : ticket USR-4, 7 sept 2026.

---

## Sécurité — connu et accepté

- [ ] **Les vues qui redéfinissent `permission_classes` sortent du dispositif de scopes**
      → État : `MeView`, `LogoutView`, le webhook de paiement et la
        synchronisation hors ligne posent leur propre `permission_classes`, ce
        qui écarte les permissions globales `HasApiScope` **et**
        `HasPlatformScope`. Conséquence mesurée : `GET /api/v1/auth/me/` répond
        200 à une `ApiCredential` tenant comme à une `PlatformCredential`, alors
        qu'aucune des deux ne devrait y accéder.
      → Portée réelle : la réponse décrit le compte technique porteur
        (`api-bot@<slug>.internal` ou `platform-bot@toupac.internal`), pas un
        humain ni des données de tenant. La fuite se limite à confirmer qu'une
        clé est valide et à révéler l'identité du bot.
      → Comportement pré-existant, découvert en écrivant les tests plateforme —
        ce n'est pas une régression introduite par ce ticket.
      → Fix : faire hériter ces vues d'une base qui conserve les permissions
        globales et n'ajoute `AllowAny`/`IsAuthenticated` qu'en complément, ou
        annoter explicitement chaque vue comme fermée aux clés.
      → Effort : ~1 h
      → Ref : `iam/tests/test_platform_permissions.py::test_platform_key_cannot_reach_endpoints_outside_the_scope_dispositif`
        (`xfail(strict=True)` documentaire — retirer le marqueur au fix).

- [ ] **`TenantMiddleware._resolve_from_header` accepte `X-Tenant-ID` sans authentification**
      → État : le middleware résout un tenant depuis `X-Tenant-ID` interprété
        comme UUID, sans contrôle d'authentification et sans garde `DEBUG`,
        alors que son docstring annonce « dev/tests uniquement ». Non
        exploitable aujourd'hui — les branches session et JWT rendent la main
        avant, et une requête anonyme échoue ensuite sur `IsAuthenticated` —
        mais la protection tient à un enchaînement, pas à une règle explicite.
      → Aggravé par ce ticket : le même en-tête porte désormais un **slug** pour
        les clés plateforme. `PlatformApiKeyAuthentication` est autoritaire (il
        réécrit `request.tenant` ou refuse), donc les deux usages coexistent
        sans faille, mais un seul en-tête pour deux formats de valeur est un
        piège pour la prochaine évolution.
      → Fix : conditionner `_resolve_from_header` à `settings.DEBUG`, ou
        renommer l'en-tête de développement (`X-Toupac-Debug-Tenant`) pour que
        `X-Tenant-ID` appartienne sans ambiguïté au contrat plateforme.
      → Effort : ~30 min
      → Ref : ticket `iam-platform-credentials`, 6 sept 2026.

---

## Tests / perf

- [ ] **Perf tests : envisager pytest-xdist + fixtures scope='session'**
      → État : suite à 42s aujourd'hui, acceptable jusqu'à ~150-200 tests 
        environ. Au-delà, la parallélisation devient rentable.
      → Fix quand seuil dépassé : `pytest-xdist` (parallélisation cœurs) + 
        extraire un `conftest_shared.py` avec fixtures immuables en scope 
        session.
      → Effort : ~1h une fois le seuil atteint
      → Ref : conversation 2 sept 2026

- [ ] **PBKDF2 sur ApiCredential.key_hash → basculer sur HMAC-SHA-256**
      → État : hash lent (adapté aux passwords humains) utilisé sur des 
        secrets API 256-bit d'entropie CSPRNG. Coût CPU inutile à chaque 
        requête authentifiée.
      → Fix : passer sur hashlib.sha256(secret.encode()).hexdigest() OU 
        HMAC-SHA-256 avec un pepper serveur. Migration : recréer les 
        clés existantes (ou support double-hash transitoire).
      → Depuis le ticket admin (5 sept 2026), chaque création de clé depuis 
        Django Admin passe aussi par `make_password()` (≈250 ms/appel). À 
        prendre en compte quand un partenaire s'onboarde avec plusieurs 
        clés d'un coup.
      → À déclencher : si latence auth API key devient visible en prod 
        (~5ms+ observé), ou si l'équipe chatbot IA se plaint de latence.
      → Effort : ~2h + coordination migration clés