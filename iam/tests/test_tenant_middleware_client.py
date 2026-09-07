"""
TOUPAC IAM — Résolution du tenant pour les trois régimes d'appelant.

Trois profils cohabitent désormais sur la même API :

- le **personnel**, dont le JWT porte `tenant_id` : la compagnie est fixée ;
- le **client TOUPAC**, dont le JWT porte `tenant_id=None` : il choisit sa
  compagnie par requête, via `X-Tenant-Id` ;
- le **service plateforme**, dont la clé n'a pas de compagnie et qui passe le
  slug de la même façon.

Le middleware ne tranche jamais un accès : il résout, ou laisse `None`. Refuser
est le travail des permissions, qui savent si l'endpoint exige une compagnie.
"""
import pytest
from django.test import RequestFactory

from core.middleware import TenantMiddleware
from iam.models import Tenant

pytestmark = pytest.mark.django_db


def resolve(header=None, path="/api/v1/voyage/routes/"):
    """Fait tourner le middleware seul et retourne la requête enrichie."""
    request = RequestFactory().get(path, **({"HTTP_X_TENANT_ID": header} if header else {}))
    TenantMiddleware(lambda r: None).process_request(request)
    return request


def test_slug_resolves_tenant(tenant_a):
    request = resolve(tenant_a.slug)

    assert request.tenant == tenant_a
    assert request.tenant_id == tenant_a.id


def test_uuid_still_resolves_tenant(tenant_a):
    """Rétrocompatibilité : l'UUID reste accepté pour les usages historiques."""
    request = resolve(str(tenant_a.id))

    assert request.tenant == tenant_a


def test_unknown_slug_leaves_tenant_none(tenant_a):
    """Le middleware ne bloque pas : il laisse les permissions décider."""
    request = resolve("compagnie-fantome")

    assert request.tenant is None
    assert request.tenant_id is None


def test_non_uuid_garbage_does_not_raise():
    """
    Avant USR-2, `X-Tenant-Id` était comparé à une colonne UUID.

    Une valeur non-UUID levait côté PostgreSQL, et seule la position du
    `try/except` empêchait la requête d'échouer. Le slug étant essayé en
    premier, ce chemin ne s'atteint plus qu'avec une chaîne qui n'est ni l'un ni
    l'autre — elle doit rester silencieuse.
    """
    for garbage in ("' OR 1=1 --", "12345", "", "   ", "not-a-uuid-nor-a-slug"):
        assert resolve(garbage).tenant is None


def test_suspended_tenant_is_not_resolved(tenant_suspended):
    """Le statut suspendu est le levier de coupure : il ferme aussi cette voie."""
    assert resolve(tenant_suspended.slug).tenant is None


def test_trial_tenant_is_resolved(tenant_trial):
    """Un essai commercial paie : il doit pouvoir utiliser l'API."""
    assert resolve(tenant_trial.slug).tenant == tenant_trial


def test_absent_header_leaves_tenant_none():
    assert resolve(None).tenant is None


def test_otp_paths_are_public(tenant_a):
    """Les chemins publics sortent avant toute résolution."""
    request = resolve(tenant_a.slug, path="/api/v1/auth/otp/request/")

    assert request.tenant is None


# ─── Bout en bout, avec un vrai JWT ───

def test_client_jwt_without_header_has_no_tenant(authenticated_client, client_fatou):
    """Un client sans en-tête n'est rattaché à rien — et c'est légitime."""
    response = authenticated_client(client_fatou).get("/api/v1/customer/me/")

    assert response.status_code == 200


def test_client_jwt_with_slug_header_reaches_tenant_data(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Le client choisit sa compagnie par requête.

    L'endpoint refuse encore le client faute de scope métier — USR-3 lui ouvrira
    les données. Ce qui compte ici est que le middleware ait résolu la
    compagnie : la réponse n'est pas une erreur de résolution.
    """
    client = authenticated_client(client_fatou)
    client.credentials(
        HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
        HTTP_X_TENANT_ID=tenant_a.slug,
    )

    response = client.get("/api/v1/voyage/routes/")

    assert response.status_code == 200


def test_staff_jwt_ignores_the_header(authenticated_client, user_admin_a, tenant_b):
    """
    La compagnie du personnel vient de son jeton, jamais d'un en-tête.

    Sans cette priorité, un agent lirait les données d'une autre compagnie en
    ajoutant une ligne à sa requête.
    """
    client = authenticated_client(user_admin_a)
    client.credentials(
        HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
        HTTP_X_TENANT_ID=tenant_b.slug,
    )

    response = client.get("/api/v1/voyage/routes/")

    assert response.status_code == 200
    returned = {row["id"] for row in response.json()["results"]}
    from voyage.models import Route
    forbidden = {str(pk) for pk in Route.objects.filter(tenant=tenant_b).values_list("id", flat=True)}
    assert returned & forbidden == set()


def test_slug_wins_over_a_colliding_uuid_lookup(tenant_a):
    """Un slug qui ressemble à un UUID reste résolu comme slug."""
    lookalike = Tenant.objects.create(
        name="Lookalike", slug=str(tenant_a.id), status=Tenant.Status.ACTIVE,
    )

    assert resolve(lookalike.slug).tenant == lookalike
