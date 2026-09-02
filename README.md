# TOUPAC — Transport Management System

TMS SaaS multi-tenant pour le transport et la logistique en Afrique de l'Ouest.

## Stack technique

- **Backend** : Django 5 + Django REST Framework + GeoDjango
- **Base de données** : PostgreSQL 16 + PostGIS 3.4
- **Cache / Broker** : Redis 7
- **Jobs async** : Celery 5
- **Conteneurisation** : Docker + Docker Compose

## Démarrage rapide (développement)

```bash
# Cloner et lancer
git clone <repo_url>
cd toupac
docker compose up -d

# Attendre que PostgreSQL soit prêt, puis :
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_workflows
docker compose exec web python manage.py seed_notification_templates
docker compose exec web python manage.py createsuperuser

# Optionnel : générer une keypair QR persistante (sinon éphémère par run)
python scripts/generate_qr_keypair.py --out-dir ./secrets/
# Puis reporter le contenu de secrets/qr_private.pem dans .env sous
# TOUPAC_QR_PRIVATE_KEY_PEM

# Accès :
# Admin     → http://localhost:8000/admin/
# API docs  → http://localhost:8000/api/docs/
# ReDoc     → http://localhost:8000/api/redoc/
# Health    → http://localhost:8000/health/
```

## Structure du projet

```
toupac/
├── config/            # Settings Django, URLs racine, Celery
├── core/              # Base technique (multi-tenant, middleware, permissions)
├── iam/               # Tenants, utilisateurs, auth JWT
├── fleet/             # Véhicules, chauffeurs, flottes
├── geo/               # Lieux (PostGIS), zones de service
├── workflow/          # Machine à états configurable
├── voyage/            # Transport passagers, réservations, contrôle embarquement
├── colis/             # Livraison de colis, dispatch, POD
├── billing/           # Facturation, paiement mobile money (Intouch)
├── tracking/          # Positions GPS, géofences, liens de suivi
├── notifications/     # Templates, envoi async (SMS, Push, WhatsApp)
└── docs/              # Documentation d'architecture
```

## API

Documentation interactive : `/api/docs/` (Swagger UI) ou `/api/redoc/` (ReDoc).

Authentification : JWT Bearer token.

```bash
# Obtenir un token
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "..."}'

# Utiliser le token
curl http://localhost:8000/api/v1/voyage/trips/ \
  -H "Authorization: Bearer <access_token>"
```

## Déploiement production

```bash
cp .env.prod.example .env.prod
# Éditer .env.prod avec les vraies valeurs
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.yml exec web python manage.py seed_workflows
docker compose -f docker-compose.prod.yml exec web python manage.py seed_notification_templates
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

## Licence

Propriétaire — tous droits réservés.
