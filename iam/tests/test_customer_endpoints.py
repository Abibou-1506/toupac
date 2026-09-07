"""
TOUPAC IAM — Endpoints du client TOUPAC.

Ces vues sont les seules à ne filtrer par aucune compagnie : elles répondent sur
la personne. C'est ce qui rend la vérification de rôle indispensable — les
ouvrir au personnel donnerait une vue transverse qu'aucun autre endpoint
n'accorde.
"""
import pytest

from iam.models import Tenant

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/customer/me/"
COMPANIES_URL = "/api/v1/customer/companies/"


def test_customer_me_returns_profile_for_client(authenticated_client, client_fatou):
    response = authenticated_client(client_fatou).get(ME_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(client_fatou.id)
    assert body["email"] == client_fatou.email
    assert body["phone"] == client_fatou.phone
    assert body["has_email"] is True
    assert body["has_phone"] is True
    assert body["notification_preferences"] == {}
    # Aucune compagnie n'est exposée : le client n'en a pas.
    assert "tenant" not in body and "tenant_id" not in body


def test_customer_me_reports_missing_contact_channels(authenticated_client):
    """`has_email` / `has_phone` disent au chatbot par quel canal proposer un code."""
    from iam.models import User

    phone_only, _ = User.get_or_create_client(phone="+221770000009")

    body = authenticated_client(phone_only).get(ME_URL).json()

    assert body["has_phone"] is True
    assert body["has_email"] is False
    assert body["email"] is None


def test_customer_me_reflects_notification_preferences(authenticated_client, client_fatou):
    client_fatou.notification_preferences = {"marketing": False}
    client_fatou.save(update_fields=["notification_preferences"])

    body = authenticated_client(client_fatou).get(ME_URL).json()

    assert body["notification_preferences"] == {"marketing": False}


@pytest.mark.parametrize("fixture_name", ["user_admin_a", "user_dispatcher_a"])
def test_customer_me_returns_403_for_staff(authenticated_client, request, fixture_name):
    staff = request.getfixturevalue(fixture_name)

    response = authenticated_client(staff).get(ME_URL)

    assert response.status_code == 403


def test_customer_me_returns_401_without_auth(api_client):
    assert api_client.get(ME_URL).status_code == 401


def test_customer_companies_lists_active_and_trial(
    authenticated_client, client_fatou, tenant_a, tenant_trial, tenant_suspended,
):
    response = authenticated_client(client_fatou).get(COMPANIES_URL)

    assert response.status_code == 200
    slugs = {company["slug"] for company in response.json()["companies"]}
    assert tenant_a.slug in slugs
    assert tenant_trial.slug in slugs
    # Proposer une compagnie suspendue ferait porter au client une panne
    # commerciale : elle refuserait la réservation.
    assert tenant_suspended.slug not in slugs


def test_customer_companies_returns_slug_name_and_country(
    authenticated_client, client_fatou, tenant_a,
):
    companies = authenticated_client(client_fatou).get(COMPANIES_URL).json()["companies"]

    entry = next(c for c in companies if c["slug"] == tenant_a.slug)
    assert entry["name"] == tenant_a.name
    assert entry["country_code"] == tenant_a.country_code


def test_customer_companies_is_sorted_by_name(authenticated_client, client_fatou):
    Tenant.objects.create(name="Zeta Transport", slug="zeta", status=Tenant.Status.ACTIVE)
    Tenant.objects.create(name="Alpha Transport", slug="alpha", status=Tenant.Status.ACTIVE)

    names = [c["name"] for c in authenticated_client(client_fatou).get(COMPANIES_URL).json()["companies"]]

    assert names == sorted(names)


def test_customer_companies_returns_403_for_staff(authenticated_client, user_admin_a):
    assert authenticated_client(user_admin_a).get(COMPANIES_URL).status_code == 403


def test_customer_companies_returns_401_without_auth(api_client):
    assert api_client.get(COMPANIES_URL).status_code == 401
