"""
TOUPAC — Fixtures pytest partagées entre tous les modules.

Placé à la racine pour que `_isolated_throttle_cache` bénéficie à tous les
tests, pas seulement à ceux de voyage/ où elle était définie initialement.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Controller

PASSWORD = "TestPass#2026"


@pytest.fixture(autouse=True)
def _celery_runs_inline(settings):
    """
    Exécute les tâches Celery dans le processus de test.

    Autouse : sans ça, `.delay()` publie sur le vrai courtier Redis, et le
    worker de développement — qui tourne à côté, sur la base de développement —
    récupère des identifiants introuvables chez lui. Le test devient dépendant
    d'un service externe pour un résultat qu'il n'observe jamais.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = False


@pytest.fixture(autouse=True)
def _isolated_throttle_cache(settings):
    """
    Isole le compteur de throttling DRF du Redis de dev.

    Autouse : un compteur qui fuit d'un test à l'autre ferait échouer les
    tests de throttle de façon non déterministe selon l'ordre d'exécution.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "toupac-tests",
        }
    }
    cache.clear()
    yield
    cache.clear()


# ─── Tenants ───

@pytest.fixture
def tenant_a():
    return Tenant.objects.create(
        name="Compagnie A", slug="compagnie-a", status=Tenant.Status.ACTIVE,
    )


@pytest.fixture
def tenant_b():
    return Tenant.objects.create(
        name="Compagnie B", slug="compagnie-b", status=Tenant.Status.ACTIVE,
    )


@pytest.fixture
def tenant_trial():
    return Tenant.objects.create(
        name="Compagnie Trial", slug="compagnie-trial", status=Tenant.Status.TRIAL,
    )


@pytest.fixture
def tenant_suspended():
    return Tenant.objects.create(
        name="Compagnie Suspendue", slug="compagnie-suspendue", status=Tenant.Status.SUSPENDED,
    )


# ─── Utilisateurs ───

def _make_user(tenant, email, role, first_name, last_name):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name=first_name, last_name=last_name,
        tenant=tenant, role=role,
        # Un admin de compagnie accède à l'admin Django (cf. seed_demo, qui pose
        # le même is_staff) — nécessaire pour tester l'isolation côté admin.
        is_staff=role == User.Role.ADMIN,
    )


@pytest.fixture
def user_admin_a(tenant_a):
    return _make_user(tenant_a, "admin.a@toupac.sn", User.Role.ADMIN, "Awa", "Diop")


@pytest.fixture
def user_admin_b(tenant_b):
    return _make_user(tenant_b, "admin.b@toupac.sn", User.Role.ADMIN, "Bintou", "Fall")


@pytest.fixture
def user_dispatcher_a(tenant_a):
    return _make_user(tenant_a, "dispatch.a@toupac.sn", User.Role.DISPATCHER, "Cheikh", "Ba")


@pytest.fixture
def user_controller_a(tenant_a):
    user = _make_user(tenant_a, "ctrl.a@toupac.sn", User.Role.CONTROLLER, "Moussa", "Sarr")
    Controller.objects.create(tenant=tenant_a, user=user, matricule="CTRL-A-01")
    return user


# ─── Clients HTTP ───

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_client():
    """
    Factory : `authenticated_client(user) -> APIClient` authentifié.

    Utilise un vrai JWT plutôt que `force_authenticate`. Ce n'est pas une
    préférence de style : `force_authenticate` pose `request.user` au niveau
    DRF, donc APRÈS le passage de TenantMiddleware, qui ne voit alors qu'un
    AnonymousUser et laisse `request.tenant = None`. Toutes les vues filtrant
    sur `tenant=self.request.tenant` renverraient un résultat vide — les tests
    d'isolation multi-tenant passeraient donc même si l'isolation était
    cassée. Vérifié : force_authenticate → 0 résultat, JWT réel → 1 résultat.

    Le JWT exerce en prime le chemin de production complet
    (middleware → simplejwt → permissions).
    """
    def _authenticated_client(user):
        client = APIClient()
        token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return _authenticated_client
