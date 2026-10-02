# Dettes techniques — TOUPAC

Dernier update : 2 oct 2026

Ce fichier consolide les dettes techniques identifiées et **délibérément 
non corrigées** pendant les tickets précédents. Chaque entrée porte : 
état actuel, approche de fix, estimation d'effort, référence.

Les dettes sont classées par domaine, pas par priorité. La priorisation 
se fait avec le lead selon le contexte produit.

---

## Sécurité

_Rien à date au-delà des points classés « connu et accepté » en fin de fichier._

---

## Modèle

- [ ] **`TenantModel` promet un filtrage automatique par tenant qui n'existe pas**
      → État : le docstring de `TenantModel` dans `core/models.py` affirme que
        « chaque requête est automatiquement filtrée par tenant_id via
        TenantQuerySetMixin et TenantMiddleware ». Il n'y a aucun
        `TenantQuerySetMixin` dans le code, et `TenantManager.get_queryset()`
        ne filtre rien. L'isolation tient uniquement aux `.filter(tenant=...)`
        écrits à la main dans chaque vue et chaque resolver.
      → Portée : un dev humain — ou une session Claude — qui lit ce docstring
        et écrit une requête `Model.objects.filter(pk=...)` en croyant à
        l'isolation automatique produit une fuite cross-tenant. Deux occurrences
        déjà nées de cet angle mort en session (`Trip.all_objects` et
        `User.all_objects` inventés, cf. débriefs E1E2 et hardening).
      → Décision (30 sept 2026) : corriger le docstring pour aligner sur la
        doctrine effective — filtrage explicite via `.filter(tenant=...)`,
        `all_objects` comme échappatoire visible. Le véritable renforcement
        (RLS PostgreSQL, voir la dette dédiée en fin de fichier) est un
        chantier séparé à moyen terme.
      → Effort : 10 min (correction docstring). Le chantier RLS est tracé à
        part.
      → Ref : découvert au débrief E1E2, confirmé au débrief hardening,
        30 sept 2026.

- [ ] **`UUIDv7Field` génère des UUID v4, contrairement à son nom**
      → État : le champ défini dans `core/models.py` s'appelle `UUIDv7Field`
        et utilise `default=uuid.uuid4`. Aucun ordonnancement temporel n'est
        produit — c'était pourtant l'intérêt du choix v7 (index B-tree
        favorable, tri chronologique naturel).
      → Impact aujourd'hui : nul. Le jour où quelqu'un s'appuiera sur
        l'ordonnancement d'un identifiant pour paginer sans curseur ou pour
        déduire une chronologie, il partira sur une base fausse.
      → Fix : soit renommer en `UUIDField` (aligner le nom sur la fonction),
        soit implémenter réellement — `uuid.uuid7` est natif en Python 3.13+,
        sinon `uuid-utils` fournit l'implémentation. La seconde option ne
        casse rien mais demande une migration : les identifiants existants
        restent v4, les nouveaux deviennent v7 — tri mélangé, à documenter.
      → Priorité : basse tant que personne n'exploite l'ordonnancement.
      → Effort : 15 min (rename) ou 1 h (implémentation + doc).
      → Ref : découvert lors de la relecture du 30 sept 2026.

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

## Documentation API

- [ ] **Le Swagger ne décrit pas les payloads polymorphes du batch offline** —
      résolu en partie le 1er oct 2026.
      - [x] **Piste 1 — exemples par event_type sur `@extend_schema`.**
            10 `OpenApiExample` en entrée (un par type), 2 en sortie (verdict
            accepté enrichi, verdict rejeté avec code + anomaly). Les
            littéraux vivent dans `voyage/schema_examples.py`, et un test de
            paramétrisation fait tourner chaque exemple contre son handler :
            un handler qui change sans mise à jour de l'exemple rend rouge.
      - [x] **Piste 2 — `ChoiceField` sur `rejection_code`.** Les 28 valeurs
            de `RejectionCode` apparaissent désormais dans le composant
            `RejectionCodeEnum` du schéma. Un test de non-régression compare
            l'énum publiée à l'énumération Python.
      - [ ] **Piste 3 — endpoint `GET /event-types/schema/`.** Reste
            ouverte, à voir dans le cadre du chantier portail intégrateurs.
            Les deux premières pistes couvrent les besoins immédiats.
      → Ref : ticket voyage-swagger-batch-doc, 1er oct 2026.

- [ ] **Spectacular — 181 warnings structurels, 4 familles à résorber**
      → État : `python manage.py spectacular --validate` termine sur 181
        warnings (64 uniques), 0 erreur. Baseline établi le 7 sept 2026
        (ticket notifications-refonte-D a fait passer de 183 à 181),
        confirmé stable à l'ouverture du Ticket 1 panel admin le 2 oct 2026.
      → Portée : le schéma OpenAPI publié décrit ces zones de manière
        appauvrie. Un client SDK généré (chatbot Toupac BI, ERP tiers
        Sage/Odoo) hérite des approximations — `PointField` typé `string`,
        énums `status`/`type` disambiguées par hash au lieu d'un nom
        lisible, auth plateforme invisible dans la doc des endpoints
        concernés — et ses utilisateurs ouvrent des tickets de support.
      → Quatre familles identifiées :
      - **A. ~50 × `PlatformApiKeyAuthentication` sans
        `OpenApiAuthenticationExtension`.** Chaque view qui déclare cette
        auth produit un warning. Fix : classe
        `PlatformApiKeyAuthenticationScheme(OpenApiAuthenticationExtension)`
        dans `iam/schema.py`, à côté de ce qui existe pour la clé tenant.
        Effort : ~1 h.
      - **B. ~10 × `PointField` / `GeoJSONField` qui tombent en
        `"string"`.** Pas de resolver typé pour les champs géo GeoDjango.
        Fix : enregistrer les extensions `drf_spectacular` pour
        `PointFieldSerializer` et `GeoJSONField` (format JSON Schema
        GeoJSON standard). Effort : ~30 min.
      - **C. ~8 collisions enum (`StatusXXXEnum`, `TypeXXXEnum`).**
        Plusieurs modèles portent un champ `status` ou `type` avec le
        même ensemble de choices ; spectacular disambigue avec un hash.
        Fix : populer `ENUM_NAME_OVERRIDES` dans `SPECTACULAR_SETTINGS`
        en nommant chaque enum par son contexte métier
        (`TripStatusEnum`, `OrderStatusEnum`, `InvoiceStatusEnum`, etc.).
        Effort : ~30 min.
      - **D. 2 × `get_context_type` / `get_context_reference` sans
        annotation `-> str`.** Pile le pattern DECISIONS.md
        « `spectacular --validate` fait partie de la routine pre-merge » :
        ces deux fonctions pré-datent la doctrine. Fix : annoter dans
        `iam/customer_serializers.py` ligne 84. Effort : 30 sec.
      → Pourquoi tracer plutôt que faire tout de suite : A + B + C mérite
        un ticket dédié où on peut tester l'avant/après du schéma généré,
        et D doit passer avec les trois autres pour avoir un snapshot
        propre. Faire D seul laisserait les trois gros contrats appauvris.
      → À déclencher : avant l'onboarding de l'équipe chatbot Toupac BI
        ou le premier client ERP tiers. Ce sont eux qui génèrent leur
        client SDK depuis `/schema/`.
      → Effort total : ~2 h en séquence (A + B + C + D).
      → Note méthodologique : `--fail-on-warn` ne distingue pas une
        régression d'une dette pré-existante. Le critère de validation
        « spectacular » dans les tickets suivants est désormais « nombre
        de warnings strictement identique au baseline », vérifié par
        `spectacular --validate 2>&1 | tail -3` sans `--fail-on-warn`.
      → Ref : audit à la fin du Ticket 1 panel admin, 2 oct 2026.

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

- [x] **~~Le destinataire d'un colis n'est modélisé nulle part~~** — le modèle
      est livré le 8 sept 2026. `Order.recipient_user`, `recipient_name` et
      `recipient_phone` existent, et les resolvers `parcel.*` s'en servent : le
      code de retrait (COL-05) a désormais quelqu'un à joindre.

      Correction de l'état décrit ici : `recipient_name` / `recipient_phone`
      vivaient sur **`ProofOfDelivery`**, pas sur la tâche de livraison — donc
      créés à la livraison, soit trop tard pour prévenir qui que ce soit.

- [x] **~~Le client destinataire ne voit toujours pas le colis dans son espace~~**
      corrigé le 1er oct 2026. `MyOrdersView` filtre désormais sur
      `Q(customer=user) | Q(recipient_user=user)` avec `.distinct()`, et
      `MyOrderSerializer` expose un champ `role` qui dit à l'app CLIENT lequel
      des deux liens le concerne — `"sender"`, `"recipient"` ou `"both"` si le
      client s'est envoyé un colis à lui-même. Vérifié sur recette : Ousmane
      voit désormais 4 commandes (2 envoyées, 2 reçues de Fatou), au lieu des
      2 d'avant.

      Reste ouvert, à décider en UI : afficher le nom de la contre-partie
      quand on est destinataire (et inversement). Vocabulaire et
      confidentialité à trancher avec le dev RN.
      → Ref : ticket customer-my-orders-with-recipient, 1er oct 2026.

- [ ] **Aucun écrivain ne renseigne `Order.recipient_user`**
      → État : le champ est nullable et reste vide sur toutes les commandes. Les
        resolvers `parcel.recipient` et `parcel.sender_and_recipient` sont donc
        justes et rendent aujourd'hui une liste vide dans la quasi-totalité des
        cas.
      → Mise à jour (1er oct 2026) : le seed de démo renseigne désormais
        `recipient_user` pour certaines commandes rattachées, pour permettre
        à l'app CLIENT en développement de tester le cas « colis reçu ».
        La vraie dette reste côté **endpoint de création** : aucun chemin
        d'écriture (admin colis, API CLIENT, chatbot) n'expose encore le champ.
      → Conséquence : **le code de retrait de colis (COL-05) ne part à
        personne**, alors même que la chaîne est complète de bout en bout. Le
        seul maillon manquant est la saisie.
      → Fix : renseigner le destinataire à la création — admin colis d'abord,
        puis les endpoints d'écriture CLIENT. Un destinataire sans compte reste
        possible : `recipient_name` / `recipient_phone` sont là pour cela.
      → Effort : ~0,5 j côté admin, davantage côté API cliente.
      → Ref : ticket E1E2, 8 sept 2026 ; mise à jour 1er oct 2026
        (ticket billing-invoice-customer-type-alignment).

- [ ] **`Payment.order` n'est renseigné par aucun seeder ni endpoint**
      → État : `MyPaymentsView` filtre les paiements via deux chemins —
        `payment.order.customer` et `payment.invoice.customer_id`. Le
        premier est inatteignable dans l'environnement de démo : aucun
        paiement n'a `order_id` renseigné. `_seed_payments` crée
        systématiquement `Payment(invoice=..., order=None)`.
      → Portée : la vue couvre correctement les deux chemins avec `.distinct()`.
        Le chemin invoice suffit tant qu'une facture est générée. Mais le jour
        où un scénario « paiement direct sans facture intermédiaire » apparaîtra
        (acompte, paiement à la livraison), l'absence de lien `order` fera que
        ces paiements n'apparaîtront pas dans l'espace client. Et le dev qui
        testera avec un paiement direct ne verra rien, sans comprendre pourquoi.
      → Fix : enrichir `_seed_payments` pour créer au moins un `Payment` avec
        `order=<Order de Fatou ou Ousmane>` et `invoice=None`, afin que le
        chemin direct soit démontrable. Et côté endpoints métier, s'assurer que
        tout paiement créé contre une commande renseigne bien `payment.order`.
      → Priorité : basse tant que tout paiement passe par une facture. Deviendra
        réelle au premier flux « paiement direct » (acompte colis, caution).
      → Effort : ~15 min (seed uniquement). Davantage le jour où un vrai
        endpoint de paiement direct existe.
      → Ref : ticket billing-invoice-customer-type-alignment, 1er oct 2026
        (découvert à la validation en recette après reset du seed).

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
      corrigé le 7 sept 2026. `ConsoleProvider` servait alors tous les canaux,
      production comprise, et `prod.py` journalise `toupac` à INFO : codes de
      connexion, QR de billets et montants partaient en clair dans la sortie
      standard. Le corps n'est désormais écrit que sous `DEBUG`. Règle
      généralisée au Ticket C : les mocks SMS et WhatsApp partagent la même
      fonction `loggable_body()`, et `EmailSmtpProvider` ne journalise jamais
      le corps.

### Notifications — centre d'alertes client

- [ ] **Aucun événement destiné à un client ne demande d'accusé de réception**
      → État : `/customer/notifications/<id>/ack/` est livré et testé, mais les
        deux seuls événements que le catalogue déclare `requires_ack=True` —
        `notif.dispatch.assigned.v1` et `notif.gps.alert.v1` — visent des
        chauffeurs et des régulateurs, jamais un client. L'endpoint est donc
        correct et inutilisable en pratique côté client aujourd'hui.
      → Ce n'est pas un défaut de l'endpoint : c'est le catalogue qui ne
        déclare encore aucun geste d'acquittement côté voyageur. Le cas viendra
        (confirmer un changement d'horaire, accepter un report).
      → Fix : rien à faire tant qu'aucun événement client ne l'exige. Décision
        du 8 sept 2026 : en veille jusqu'au design de l'app mobile CLIENT, qui
        décidera quels gestes d'acquittement lui sont nécessaires. Le câblage
        des resolvers (E1E2, livré le 8 sept) est passé sans que le besoin
        n'émerge côté métier.
      → Effort : nul aujourd'hui.
      → Ref : ticket notifications-refonte-D, 7 sept 2026 ; révisé 8 sept 2026
        puis 30 sept 2026.

- [ ] **L'espace client mélange endpoints paginés et non paginés**
      → État : `/customer/notifications/` pagine (20 par page, 50 au plus) ;
        `/my-reservations/`, `/my-orders/` et `/my-payments/` rendent la
        collection entière. Un client de l'API doit donc traiter deux formes de
        réponse selon l'endroit.
      → Pourquoi c'est ainsi : le centre d'alertes est le seul dont le volume
        croît sans borne — un client accumule des alertes sans jamais en
        supprimer, là où ses réservations restent en dizaines.
      → Fix : paginer les trois autres avec la même classe, en gardant la
        collection nommée. Rupture de contrat pour les consommateurs existants
        (le chatbot Toupac BI), donc à annoncer, pas à glisser.
      → Effort : ~0,5 j + coordination avec les consommateurs.
      → Ref : ticket notifications-refonte-D, 7 sept 2026.

- [ ] **Rien ne purge les notifications lues**
      → État : `Notification.expires_at` existe et n'est lu par personne. Une
        ligne reste en base indéfiniment, lue ou non.
      → Portée : le centre d'alertes d'un client actif grossira sans limite, et
        le filtre `?category=` traduit déjà la catégorie en liste de codes —
        requête dont le coût suivra le volume.
      → Fix : tâche périodique de purge, à traiter avec la rétention générale
        du journal d'envoi (voir la dette sur `NotificationLog.content`), les
        deux relevant de la même décision de conservation.
      → Effort : ~0,5 j pour les deux ensemble.
      → Ref : ticket notifications-refonte-D, 7 sept 2026.

### Notifications — écarts avec la charte TOUPAC ONE

Cross-check complété le 8 sept 2026 après lecture intégrale du fichier
`Charte_notifications_TOUPAC_ONE.xlsx` (4 feuilles : Charte, Référentiel
plateformes, Matrice notifications, Gabarits messages). Les 37 events sont
bien tous déclarés au catalog avec bon `charte_id`, priorité, canaux
principaux. Ce qui suit sont les écarts identifiés, classés par urgence.

#### Écarts relevés au câblage des resolvers (8 sept 2026)

- [ ] **COL-03 : la charte dit « Client », le catalogue dit `parcel.recipient`**
      → État : l'événement « ETA mise à jour » est déclaré avec le resolver
        `parcel.recipient`, donc part au seul destinataire. Or les autres lignes
        de la feuille assimilent « Client » à l'expéditeur — COL-02 dit
        explicitement « Client / expéditeur ». Une ETA intéresse
        vraisemblablement les deux.
      → Non tranché ici : arbitrer relève du produit, pas du câblage. Le ticket
        implémente ce que déclare le catalogue.
      → Fix probable : basculer COL-03 sur `parcel.sender_and_recipient`. Un
        mot du resolver à changer, aucune migration.
      → Effort : ~15 min une fois la décision prise.
      → Ref : ticket E1E2, 8 sept 2026.

- [ ] **`assignment_id` (DSP-01, DSP-02) ne référence aucun modèle**
      → État : les deux événements déclarent `assignment_id: uuid` en variable
        de gabarit. **Aucune classe `Assignment` n'existe** dans l'arborescence
        — l'affectation d'un chauffeur à un voyage se lit sur `Trip.driver`, qui
        pointe sur `fleet.Driver`, sans entité d'affectation propre.
      → Conséquence limitée : c'est une variable de rendu, pas de résolution.
        Le resolver `dispatch.driver` s'appuie sur `driver_user_id`, qui lui
        désigne bien un compte. L'émetteur devra néanmoins fournir un UUID qui
        ne référence rien.
      → Fix : soit modéliser l'affectation (chantier), soit retirer la variable
        du catalogue en v2 de ces deux événements. À trancher avec le lead.
      → Effort : selon la décision.
      → Ref : ticket E1E2, 8 sept 2026.

- [ ] **Dix rôles de la charte n'existent pas dans `User.Role`, et sont repliés**
      → État : responsable flotte, mécanicien, magasinier, acheteur,
        approbateur, financier, responsable gare, superviseur, IT et direction
        sont repliés sur `ADMIN`, `AGENT` ou `DISPATCHER`. Chaque resolver
        concerné le dit en commentaire, et `test_resolvers_operations_transverse.py`
        fixe le repli dans un tableau.
      → Conséquence : plusieurs notifications d'exploitation arrivent chez
        l'administrateur de la compagnie, qui recevra donc beaucoup. Acceptable
        pour des compagnies de la taille visée, moins au-delà.
      → Fix : étendre `User.Role`, chantier produit à part entière — pas un
        effet de bord d'un ticket de câblage. `gps.dispatchers_and_fleet` et
        `gps.dispatchers_and_it` sont volontairement restés deux fonctions
        distinctes malgré une population identique, pour que le redécoupage
        n'ait qu'un endroit à toucher.
      → Effort : ~2 j, plus la migration des comptes existants.
      → Ref : ticket E1E2, 8 sept 2026.

#### Deux quick wins intégrés au Ticket F

Regroupés au Ticket F (seed templates) puisqu'ils touchent au même code et
prennent < 1h chacun. NE PAS OUBLIER en rédigeant le prompt F.

- **N-05 masquage du sujet email**. La charte dit textuellement « Aucun
  OTP, donnée bancaire, document d'identité ou adresse complète dans le
  push **ou l'objet e-mail** ». Le Ticket B a assumé « email = payload
  complet » sans distinguer le sujet du corps. Un email « Confirmation
  paiement 25 000 FCFA » en sujet est visible en aperçu lockscreen Gmail
  sur téléphone. Fix : appliquer les `confidentiality_masks` au **sujet**
  email (pas au corps), en complément de push+SMS+WhatsApp.
  → Effort : ~30 min dans `notifications/rendering.py`.

- **Contraintes de longueur push**. La charte dit « Titre <= 45 char, corps
  <= 140 char » pour les push. `NotificationTemplate.title_template` est
  CharField(200), `template_body` est TextField sans limite. Un template
  long produit un push qui sera tronqué par FCM/APNs au moment de l'envoi
  (perte de sens). Fix : validation dans `NotificationTemplate.clean()`
  qui refuse un template push dépassant les limites au rendu (avec un
  contexte de test).
  → Effort : ~30 min.

#### Chantier « conformité charte complète » — Phase E du plan

Gros chantier ~5-6 jours à ouvrir après user management + endpoints
écriture CLIENT + backoffice frontend. Bloquant pour vraie mise en
production, non bloquant pour démo lead ou premières compagnies pilotes.

- [ ] **N-07 temporisation / agrégation** — la charte demande « regrouper
      les changements rapprochés non critiques ».
      → Concernés : COL-03 (positions GPS colis, non spammer), TRJ-03
        (mises à jour retard à regrouper si ETA ré-évolue), STK-01
        (regrouper par site/catégorie), APR-01 (pas de relances
        excessives), CMD-02 (une relance maximum), PAY-02 (éviter la
        notification sur simple timeout temporaire).
      → Fix : mécanisme de déduplication temporelle « une notif toutes les
        N min pour un même (event, user) » au niveau service. Fenêtre
        paramétrée dans le catalog (`throttle_minutes: int | None`).
        Redis clef courte pour tracking. Distinct de l'idempotence 24h.
      → Effort : ~1-2 j.

- [ ] **N-03 langue utilisateur non résolue**
      → État : `emit(language="fr")` accepte le paramètre mais il faut le
        passer manuellement, jamais résolu depuis le destinataire. Un
        futur CLIENT anglophone (Ghana, Nigéria) recevrait tout en
        français.
      → Fix : ajouter `User.language` (CharField(2), défaut "fr"),
        migration, résolution automatique dans `emit()` à partir du
        recipient.
      → Effort : ~1 j (modif modèle + migration + service + tests).

- [ ] **Délais programmés / scheduler manquant**
      → État : la charte spécifie « Immédiat », « < 1 min », mais aussi
        « T-15 min » (avant expiration réservation), « T-24 h et T-1h »
        (rappel départ), « J-30, J-15, J-1 » (maintenance / conformité).
        Notre `emit()` envoie tout immédiatement.
      → Concernés : TRJ-01 (rappel départ T-24h/T-1h), FLT-01 (maintenance
        J-30/J-15/J-1), CMP-01 (document expirant J-30/J-15/J-1), CMD-02
        (réservation expirant T-15min).
      → Fix : commande Celery beat qui scanne périodiquement les entités
        métier et déclenche `emit()` aux bons moments. Pattern lookup :
        `Trip.objects.filter(departure_at__range=(now+23h, now+25h))`
        pour le T-24h.
      → Effort : ~1 j (Celery beat + 4 scheduler tasks + tests).

- [ ] **Ack au déclarant (INC-01, CRM-01)**
      → État : INC-01 dit « Accusé de réception push au déclarant ».
        Notre resolver `incident.dispatchers_and_admin` envoie à tous
        les dispatchers/admins, pas garanti au déclarant spécifiquement.
        Le déclarant reçoit peut-être la notif s'il est dispatcher, mais
        c'est fortuit.
      → Fix : ajouter un event complémentaire `notif.incident.
        acknowledgment.v1` avec `resolver_key="incident.reporter"` +
        `requires_ack=True`, déclenché en même temps que INC-01. Même
        pattern pour CRM-01.
      → Effort : ~0,5 j (2 events + resolvers + tests).

- [ ] **MKT-01 plafonnement fréquence + non-relance post-conversion**
      → État : « plafonner la fréquence et ne pas relancer après
        conversion ou expiration » non traité. Un client qui a utilisé un
        code promo continue de recevoir des rappels.
      → Fix : nouveau modèle `MarketingCampaign.excluded_users` ou
        mécanisme de blacklist temporaire par campagne. À détailler avec
        le lead — dépend de la stratégie CRM.
      → Effort : ~1 j.

- [ ] **Rate limiting métier**
      → État : l'idempotency Redis 24h évite les doublons stricts d'un
        même event, mais ne bloque pas une nouvelle relance volontaire
        (CMD-02 « une relance maximum », PAY-02 « éviter timeout
        temporaire », APR-01 « pas de relances excessives »).
      → Fix : compteur Redis par (event_code, user_id) avec fenêtre
        glissante, refusé au-delà d'un plafond déclaré au catalog
        (`max_sends_per_day: int | None`).
      → Effort : ~1 j.

**Priorité produit implicite** : les 5 points ci-dessus dans l'ordre
listé (N-07 en premier car impact utilisateur direct spam). À discuter
avec le lead avant ouverture du chantier — certains peuvent être
reportés V2 selon le contexte commercial.

### Notifications — passerelles réelles

- [ ] **Trois canaux sur cinq ne délivrent rien**
      → État : depuis le Ticket C, chaque canal a son provider et l'e-mail part
        pour de bon via `django.core.mail`. Push, SMS et WhatsApp restent des
        simulations, qui s'annoncent comme telles (`fake_fcm_…`, `sms_mock`,
        `whatsapp_mock`) au lieu de se faire passer pour des envois.
      → Conséquence directe : **la connexion par code ne fonctionne pas pour un
        client sans adresse e-mail.** Le code est bien généré et tracé, mais
        aucun SMS ne part. C'est le chemin nominal d'une bonne partie de la
        clientèle visée.
      → Fix : un ticket par passerelle, chacun conditionné à un compte et un
        budget — Firebase (push), Africa's Talking / Twilio / D7Networks (SMS),
        Twilio WhatsApp ou Meta Cloud API (WhatsApp). Côté code, chacun se
        réduit à une classe et une ligne de `NOTIFICATION_PROVIDERS`.
      → Effort : ~1 j par passerelle, hors création de compte et validation des
        gabarits Meta pour WhatsApp.
      → Ref : ticket notifications-refonte-C, 7 sept 2026.

**Priorité produit implicite** (à valider avec le lead) : SMS d'abord (auth
CLIENT), puis WhatsApp, puis Push. Le SMS débloque la connexion par code
pour la majorité de la clientèle ouest-africaine — les deux autres sont des
enrichissements produit.

#### Choix du fournisseur SMS — comparaison pour à valider avec le lead

Trois candidats couramment cités pour l'Afrique de l'Ouest. Aucun n'a été
testé côté TOUPAC — le lead a la relation commerciale.

| Critère | Africa's Talking | Twilio | D7Networks |
|---|---|---|---|
| Couverture UEMOA (Orange, Free, MTN, Expresso, Malitel) | Historique fort, spécialiste Afrique | Universel, tous opérateurs | Bonne couverture, prix agressif |
| Coût indicatif SMS SN | ~10-15 FCFA | ~25-40 FCFA | ~8-12 FCFA |
| API REST classique | Oui, doc lisible | Oui, SDK Python officiel | Oui, doc en anglais |
| Sender ID alphanumérique (« TOUPAC » au lieu d'un numéro) | Oui, sur demande | Oui, payant | Oui, gratuit |
| Rapports de livraison (webhook) | Oui | Oui | Oui |
| Contrats/facturation UEMOA (XOF, TVA locale) | Oui (bureau Nairobi) | Non (facture USD) | Non (facture USD) |

Ma reco personnelle si le lead n'a pas de préférence : **Africa's Talking**
pour la spécialisation région + facturation XOF native. Twilio si le
partenaire chatbot demande la même passerelle qu'il utilise déjà ailleurs.
D7Networks si coût déterminant.

#### Cadrage du ticket SMS-real, prêt quand la clé arrive

Quand le lead te transmet un identifiant + une clé API SMS (peu importe le
fournisseur), le ticket suivant se résume à :

1. **Créer `notifications/providers/sms_<fournisseur>.py`** (ex.
   `sms_africas_talking.py`) qui hérite de `NotificationProvider` et
   appelle l'API HTTP du fournisseur via `requests` (ou SDK officiel).
2. **Retourner `NotificationResult(success, provider="sms_<slug>",
   provider_message_id=<id API>)`.** En cas d'échec HTTP, propager
   l'exception — la retry policy du canal SMS (`retries.py`) est
   actuellement à 0 retry par coût (à rediscuter selon le fournisseur).
3. **Ajouter les clés API dans `.env.prod`** avec un préfixe
   `SMS_<SLUG>_API_KEY`, lues dans `config/settings/prod.py`.
4. **Overrider `NOTIFICATION_PROVIDERS["sms"]`** en `prod.py` vers le
   nouveau provider. `dev.py` continue avec `SmsConsoleProvider` mock.
5. **Ajouter un webhook de statut delivery** (voir dette suivante). Peut
   être fait séparément.
6. **Tests** : mocker `requests.post` en test unitaire, un test
   d'intégration `manage.py send_test_sms +221...` en commande admin
   pour vérifier sur serveur dev avec la vraie API en pré-prod.

Effort : ~1 j Sonnet 4.5 une fois la clé API en main.

#### Cadrage WhatsApp — à traiter après SMS

Attention spécifique WhatsApp Business :
- Impose des **templates de message pré-approuvés par Meta** pour tout
  envoi initié par l'entreprise (window de 24h après un message user
  suspend cette contrainte, mais l'OTP est toujours initié par nous).
- Validation Meta prend 1-3 jours ouvrés.
- Twilio WhatsApp ou Meta Cloud API directe — Twilio simplifie
  l'onboarding, Meta Cloud API coûte moins cher.
- Coût ~4-5x un SMS classique selon pays.

Pré-requis avant d'ouvrir le ticket WhatsApp : compte Meta Business
validé, templates OTP soumis et approuvés, clé API disponible.

- [ ] **`.env.prod` ne configure aucun serveur SMTP**
      → État : `prod.py` déclare le backend SMTP et lit `EMAIL_HOST`,
        `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`. Aucune n'est
        renseignée. Tout envoi e-mail en production lèvera, épuisera ses trois
        réessais et finira tracé en échec.
      → C'est voulu et préférable à l'état antérieur, où l'envoi se déclarait
        réussi sans que rien ne parte. Mais l'échec est réel : à renseigner
        avant toute mise en service.
      → Effort : ~0,5 j (choix du fournisseur, DNS SPF/DKIM, variables).
      → Ref : ticket notifications-refonte-C, 7 sept 2026.

- [ ] **Aucun retour de livraison n'est collecté**
      → État : `NotificationLog.sent_at` dit qu'un fournisseur a accepté le
        message, pas qu'il a été remis. Les vraies passerelles exposent des
        webhooks de statut (remis, rebond, plainte) que rien ne consomme.
      → Portée : sans cela, une adresse morte ou un numéro invalide reste
        indéfiniment considéré comme joignable, et les rebonds répétés abîment
        la réputation d'envoi du domaine.
      → Fix : à traiter avec la première passerelle réelle, pas avant — la forme
        du webhook dépend du fournisseur retenu.
      → Effort : ~1 j
      → Ref : ticket notifications-refonte-C, 7 sept 2026.

### Voyage — protocole offline des events de contrôle

- [ ] **Une panne passagère condamne définitivement un event**
      → État : l'event est archivé **avant** d'être traité — c'est lui qui porte
        l'idempotence. Si le handler échoue sur une cause transitoire (base
        momentanément indisponible, verrou), le verdict est
        `INTERNAL_ERROR` mais la ligne `ControlEvent` existe, avec son
        `client_uuid`. Au rejeu du batch, le contrôle d'idempotence la retrouve
        et rend « duplicate » : **l'event ne pourra plus jamais aboutir**.
      → Portée : la vente à bord et l'embarquement sont concernés. L'argent
        encaissé sur le terrain n'aurait alors aucune contrepartie en base, et
        rien ne le signalerait à l'app, qui voit un doublon — donc un succès.
      → Ce que le Ticket C a apporté : `INTERNAL_ERROR` et `UNPROCESSABLE_EVENT`
        se distinguent enfin, le second désignant un event jamais archivé, donc
        rejouable. Le premier reste piégé.
      → Fix envisagé : ne pas figer l'idempotence sur un rejet dû à une panne —
        soit en supprimant l'event archivé dans cette seule branche, soit en
        marquant la ligne « à rejouer » et en l'excluant du contrôle. La
        première option perd la trace de l'incident, la seconde la garde ; c'est
        la seconde qu'il faut, et elle demande un champ de plus.
      → Effort : ~0,5 j, plus une décision sur ce que l'app doit faire d'un
        verdict rejouable — ce qui rejoint la question du `retryable` écartée du
        Ticket C.
      → Ref : ticket voyage-batch-hardening, 30 sept 2026.

- [ ] **Le montant d'une vente à bord n'est confronté à aucun tarif**
      → État : `amount_xof` est enregistré tel que l'app l'envoie. Le manifeste
        expose pourtant un `pricing.default_price_xof`, que rien ne compare.
      → Pourquoi ce n'est pas un défaut : une vente à bord s'écarte
        légitimement du tarif nominal — trajet partiel, arrangement, geste
        commercial. Refuser l'écart casserait le métier.
      → Fix souhaitable : ne pas refuser, mais **tracer**. Une anomalie
        d'écart au-delà d'un seuil donnerait à l'exploitation ce qu'elle n'a pas
        aujourd'hui : la visibilité sur les ventes hors tarif, qui est le seul
        endroit où une fraude au guichet mobile peut se loger.
      → Effort : ~0,5 j, après décision produit sur le seuil.
      → Ref : ticket voyage-batch-hardening, 30 sept 2026.

- [ ] **Une vente à bord ne rattache jamais le passager à son compte client**
      → État : `handle_onboard_sale` crée un `Passenger` sans `customer_user`,
        même quand le téléphone fourni correspond à un compte TOUPAC existant.
        Le voyageur ne verra pas ce billet dans `/customer/my-reservations/`.
      → À rapprocher de la réutilisation de fiche déjà en place : le handler
        retrouve un `Passenger` par téléphone, mais pas un `User`.
      → Fix : chercher aussi un compte client par ce téléphone et le rattacher.
        Attention — c'est la même question que le rattachement d'un second canal
        (voir plus haut) : croire un numéro sur parole ouvre une prise de
        contrôle à qui le devine. À trancher ensemble, pas séparément.
      → Effort : ~0,5 j une fois la règle d'identité tranchée.
      → Ref : ticket voyage-batch-hardening, 30 sept 2026.

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

- [x] **~~Les resolvers `parcel.*` ne vérifient pas que l'`order_id` appartient au tenant courant~~**
      corrigé le 30 sept 2026. Le helper `_order()` exige désormais `tenant`
      et filtre dessus, les trois resolvers le passent, quatre tests
      d'isolation croisent les deux tenants. Un `order_id` d'une autre
      compagnie rend `[]`, silencieusement — cohérent avec la doctrine « une
      résolution vide se journalise sans devenir un échec ». La dette
      transverse « `TenantModel` ne filtre pas de lui-même » reste ouverte —
      cette entrée n'en soigne qu'un cas.
      → Ref : ticket notifications-parcel-tenant-guard, 30 sept 2026.

- [ ] **Chantier `security-postgres-rls` — renforcement de l'isolation tenant**
      → État : l'isolation cross-tenant tient aux `.filter(tenant=...)` écrits
        à la main dans chaque vue, chaque resolver, chaque commande de
        management. Trois occurrences d'oubli déjà recensées (`parcel.*` sans
        garde tenant, deux inventions de managers en session). À mesure que
        le code grandit, la surface d'erreur croît linéairement.
      → Pourquoi RLS : une policy PostgreSQL Row-Level Security par table
        filtre par tenant côté base, indépendamment du code Django. Même un
        SQL brut manuel est protégé. C'est le patron retenu par Notion,
        Auth0, Linear en production sur des architectures shared-schema.
      → Fix : middleware qui pose `SET LOCAL app.current_tenant = '<uuid>'`
        au début de chaque requête authentifiée, policies RLS par table
        tenantée, tests d'isolation croissés. Attention PgBouncer transaction
        mode qui casse `SET LOCAL` par défaut — vérifier la config prod.
      → Priorité : moyenne. Non urgent tant qu'on a un seul tenant de démo,
        réelle avant l'onboarding de la deuxième compagnie payante — c'est
        alors un client qui paye pour son isolation.
      → Effort : ~2-3 j (POC sur une table + audit + généralisation). Une
        session peut cadrer avant.
      → Ref : décision d'audit du 30 sept 2026, cf. dette `TenantModel`.

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

- [x] **~~Suite pytest à 6 min 18 — seuil franchi~~** — résolu par
      pytest-xdist le 2 oct 2026. 910 tests, 1 xfailed en **2 min 22 s** sur
      une machine 14 cœurs via `-n auto --dist=loadfile`. Gain **-62 %** vs
      la baseline DETTES.md du 2 oct matin (6 min 18 — note : baseline
      remesurée au moment du ticket perf à 3 min 46 sur ce poste, la
      référence 6 min 18 provenait d'un run antérieur sur une charge
      container différente ; dans tous les cas, régime passé sous le seuil
      des 5 min, le dev relance en local avant de commit sans la pression
      des 6 min). pytest-testmon reste une étape future si la trajectoire
      reprend au-dessus de 5 min.
      → Ref : micro-ticket perf-pytest-xdist, 2 oct 2026.

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