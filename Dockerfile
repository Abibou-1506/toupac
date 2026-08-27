FROM python:3.12-slim AS base

# Dépendances système pour PostGIS
# - curl : healthcheck HTTP (web, ws)
# - procps (pgrep) : healthcheck liveness (beat — pas de ping applicatif possible, cf. compose)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    gcc libpq-dev curl procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installer les dépendances Python (couche cachée)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Collecter les fichiers statiques
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-placeholder \
    python manage.py collectstatic --no-input 2>/dev/null || true

# Créer un user non-root
RUN useradd -m -r toupac && chown -R toupac:toupac /app
USER toupac

EXPOSE 8000

# Pas de HEALTHCHECK ici : cette image sert 4 rôles différents (web, worker,
# beat, ws) qui ne partagent ni port ni protocole de vérification. Un check
# unique au niveau image serait faux pour au moins 3 des 4 — chaque service
# déclare le sien dans docker-compose.prod.yml, où le rôle est connu.

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker"]
