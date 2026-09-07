"""
TOUPAC IAM — Permissions plateforme : scopes et contrat du header X-Tenant-ID.

Le contrat de header est volontairement un 400 et non un 403 : oublier
`X-Tenant-ID` est une requête mal formée, pas un défaut d'autorisation, et un
403 enverrait l'intégrateur chercher un scope manquant sans rapport.
"""
import pytest

from iam.tests.platform_helpers import (
    TEST_IP,
    make_credential,
    platform_client,
)

pytestmark = pytest.mark.django_db

ROUTES_URL = "/api/v1/voyage/routes/"
ORDERS_URL = "/api/v1/colis/orders/"
TENANTS_URL = "/api/v1/platform/tenants/"
HEALTH_URL = "/api/v1/platform/health/"
NOTIFICATIONS_URL = "/api/v1/platform/notifications/"


def test_scope_missing_from_credential_refused(tenant_a):
    """Une clé sans `platform:voyage:read` ne lit pas les routes."""
    _, secret = make_credential(scopes=["platform:colis:read", "platform:global:read"])

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_scope_present_grants_access(tenant_a):
    _, secret = make_credential(scopes=["platform:voyage:read"])

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200


def test_scopes_are_per_domain(tenant_a):
    """Un scope voyage n'ouvre pas colis : pas de fuite entre domaines."""
    _, secret = make_credential(scopes=["platform:voyage:read"])
    client = platform_client(secret, tenant_a.slug)

    assert client.get(ROUTES_URL, REMOTE_ADDR=TEST_IP).status_code == 200
    assert client.get(ORDERS_URL, REMOTE_ADDR=TEST_IP).status_code == 403


def test_tenant_scopes_do_not_satisfy_platform_checks(tenant_a):
    """
    Une clé plateforme portant un scope tenant serait refusée.

    Les deux familles sont étanches : `voyage:read` n'est pas
    `platform:voyage:read`. Le modèle refuse d'ailleurs ce scope à l'émission —
    on vérifie ici l'étanchéité côté permission, sur une clé forcée en base.
    """
    from iam.models import PlatformCredential

    credential, secret = make_credential(scopes=["platform:global:read"])
    PlatformCredential.objects.filter(pk=credential.pk).update(
        platform_scopes=["voyage:read", "admin:*"],
    )

    response = platform_client(secret, tenant_a.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_write_without_an_acting_user_is_refused_even_with_every_scope(tenant_a):
    """
    Tous les scopes ne suffisent pas : une écriture exige un client désigné.

    L'écriture est ouverte depuis USR-4, mais toujours au nom de quelqu'un —
    l'attribuer au porteur technique produirait une commande sans titulaire.
    """
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).post(
        ORDERS_URL, {}, format="json", REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "X-Acting-User-Email" in response.json()["detail"]


def test_global_endpoint_refuses_x_tenant_id(tenant_a):
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 400
    assert "X-Tenant-ID" in str(response.json())


def test_global_endpoint_without_header_succeeds():
    _, secret = make_credential()

    response = platform_client(secret).get(TENANTS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 200


def test_tenant_endpoint_refuses_missing_x_tenant_id():
    _, secret = make_credential()

    response = platform_client(secret).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 400
    assert "X-Tenant-ID" in str(response.json())


def test_tenant_endpoint_refuses_an_unknown_company():
    """La compagnie doit exister et être active — c'est le seul filtre qui reste."""
    _, secret = make_credential()

    response = platform_client(secret, "compagnie-fantome").get(
        ROUTES_URL, REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "compagnie-fantome" in response.json()["detail"]


def test_any_active_company_is_reachable_without_prior_authorisation(tenant_a, tenant_b):
    """
    Aucune habilitation par compagnie depuis USR-4.

    Une clé atteint toute compagnie active, et le cloisonnement reste porté par
    ses scopes — pas par une liste d'abonnées.
    """
    _, secret = make_credential(scopes=["platform:voyage:read"])

    for tenant in (tenant_a, tenant_b):
        response = platform_client(secret, tenant.slug).get(ROUTES_URL, REMOTE_ADDR=TEST_IP)
        assert response.status_code == 200


def test_unannotated_endpoint_is_closed_by_default(tenant_a):
    """
    Un endpoint qui ne déclare aucun scope reste fermé aux clés plateforme.

    `/api/v1/notifications/templates/` participe au dispositif (il n'écrase pas
    `permission_classes`) mais ne déclare ni `api_scope_domain` ni
    `platform_required_scope` : le refus par défaut doit s'appliquer, sans quoi
    un oubli d'annotation ouvrirait l'endpoint au lieu de le fermer.
    """
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get(
        "/api/v1/notifications/templates/", REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403


@pytest.mark.xfail(
    strict=True,
    reason="Dette connue et pré-existante : les vues qui redéfinissent "
           "permission_classes (MeView, logout, webhook, batch offline) sortent du "
           "dispositif de scopes — ni HasApiScope ni HasPlatformScope ne s'y appliquent. "
           "Vérifié : une ApiCredential tenant obtient elle aussi 200. La fuite se "
           "limite à l'identité du compte technique porteur, aucune donnée de tenant. "
           "Tracé dans DETTES.md ; retirer ce marqueur quand le trou sera fermé.",
)
def test_platform_key_cannot_reach_endpoints_outside_the_scope_dispositif(tenant_a):
    _, secret = make_credential()

    response = platform_client(secret, tenant_a.slug).get("/api/v1/auth/me/", REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_notifications_endpoint_requires_its_own_scope(tenant_a):
    _, secret = make_credential(scopes=["platform:voyage:read"])

    response = platform_client(secret, tenant_a.slug).get(NOTIFICATIONS_URL, REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403


def test_permissions_do_not_affect_jwt_users(tenant_a, user_admin_a, authenticated_client):
    """Les dispositifs plateforme sont sans effet sur une requête JWT ordinaire."""
    response = authenticated_client(user_admin_a).get(ROUTES_URL)

    assert response.status_code == 200


# ─── Écriture métier (ouverte par USR-4) ───

RESERVATIONS_URL = "/api/v1/voyage/reservations/"


def test_write_requires_the_domain_write_scope(tenant_a, client_fatou):
    _, secret = make_credential(scopes=["platform:voyage:read", "platform:customer:read"])

    response = platform_client(
        secret, tenant_a.slug, acting_email=client_fatou.email,
    ).post(RESERVATIONS_URL, {}, format="json", REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
    assert "platform:voyage:write" in response.json()["detail"]


def test_write_requires_an_acting_user(tenant_a):
    """
    Écrire sans savoir pour qui attribuerait l'enregistrement au porteur technique.

    Le refus porte sur l'absence de client désigné, pas sur un scope : le message
    doit nommer l'en-tête manquant.
    """
    _, secret = make_credential(scopes=["platform:voyage:read", "platform:voyage:write"])

    response = platform_client(secret, tenant_a.slug).post(
        RESERVATIONS_URL, {}, format="json", REMOTE_ADDR=TEST_IP,
    )

    assert response.status_code == 403
    assert "X-Acting-User-Email" in response.json()["detail"]


def test_write_passes_the_permission_layer_when_both_conditions_hold(tenant_a, client_fatou):
    """
    Scope et client désigné réunis, la permission laisse passer.

    Le corps vide échoue ensuite en validation de champs — un 400, et non un
    403, prouve qu'on a franchi la couche d'autorisation.
    """
    _, secret = make_credential(
        scopes=["platform:voyage:read", "platform:voyage:write", "platform:customer:read"],
    )

    response = platform_client(
        secret, tenant_a.slug, acting_email=client_fatou.email,
    ).post(RESERVATIONS_URL, {}, format="json", REMOTE_ADDR=TEST_IP)

    assert response.status_code == 400


def test_a_domain_without_a_write_scope_stays_closed(tenant_a, client_fatou):
    """
    `platform:tracking:write` n'existe pas : aucune clé ne peut le porter.

    Le refus est automatique, sans liste d'exceptions à tenir à jour — c'est ce
    qui rend l'ouverture de l'écriture sûre domaine par domaine.
    """
    from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES

    assert "platform:tracking:write" not in PLATFORM_AVAILABLE_SCOPES

    _, secret = make_credential(scopes=["platform:tracking:read", "platform:customer:read"])
    response = platform_client(
        secret, tenant_a.slug, acting_email=client_fatou.email,
    ).post("/api/v1/tracking/positions/", {}, format="json", REMOTE_ADDR=TEST_IP)

    assert response.status_code == 403
