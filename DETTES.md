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

## Tests / perf

- [ ] **Perf tests : envisager pytest-xdist + fixtures scope='session'**
      → État : suite à 42s aujourd'hui, acceptable jusqu'à ~150-200 tests 
        environ. Au-delà, la parallélisation devient rentable.
      → Fix quand seuil dépassé : `pytest-xdist` (parallélisation cœurs) + 
        extraire un `conftest_shared.py` avec fixtures immuables en scope 
        session.
      → Effort : ~1h une fois le seuil atteint
      → Ref : conversation 2 sept 2026