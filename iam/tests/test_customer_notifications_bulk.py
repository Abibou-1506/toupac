"""
TOUPAC IAM — Le compte non lu et le « tout marquer lu ».

Deux endpoints qui n'existent que pour l'interface : une pastille, et le geste
qui la remet à zéro. Tous deux transverses aux compagnies, sans filtre — un
compte partiel n'aurait aucun sens sur une pastille.
"""
import pytest
from django.utils import timezone

from iam.models import User
from iam.tests.customer_factories import make_notification

pytestmark = pytest.mark.django_db

UNREAD_URL = "/api/v1/customer/notifications/unread-count/"
MARK_ALL_URL = "/api/v1/customer/notifications/mark-all-read/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


# ─── La pastille ───

def test_the_unread_count_ignores_what_has_been_read(
    authenticated_client, client_fatou, tenant_a,
):
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_a, client_fatou, read_at=timezone.now())

    body = authenticated_client(client_fatou).get(UNREAD_URL).json()

    assert body == {"unread_count": 2}


def test_the_unread_count_spans_every_company(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_b, client_fatou)

    assert authenticated_client(client_fatou).get(UNREAD_URL).json()["unread_count"] == 2


def test_the_unread_count_ignores_other_clients(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    make_notification(tenant_a, client_aicha)

    assert authenticated_client(client_fatou).get(UNREAD_URL).json()["unread_count"] == 0


# ─── Tout marquer lu ───

def test_marking_all_read_touches_only_the_unread(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Repasser sur les lignes déjà lues écraserait la date de première
    consultation — la seule que ce champ ait vocation à porter.
    """
    from datetime import timedelta

    earlier = timezone.now() - timedelta(days=1)
    already_read = make_notification(tenant_a, client_fatou, read_at=earlier)
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_a, client_fatou)

    response = authenticated_client(client_fatou).post(MARK_ALL_URL)

    assert response.status_code == 200
    assert response.json() == {"marked_read": 2}
    already_read.refresh_from_db()
    assert already_read.read_at == earlier
    assert authenticated_client(client_fatou).get(UNREAD_URL).json()["unread_count"] == 0


def test_marking_all_read_spans_every_company(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_b, client_fatou)

    assert authenticated_client(client_fatou).post(MARK_ALL_URL).json() == {
        "marked_read": 2,
    }


def test_marking_all_read_when_nothing_is_unread_returns_zero(
    authenticated_client, client_fatou, tenant_a,
):
    make_notification(tenant_a, client_fatou, read_at=timezone.now())

    assert authenticated_client(client_fatou).post(MARK_ALL_URL).json() == {
        "marked_read": 0,
    }


def test_marking_all_read_leaves_other_clients_alone(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """Un « tout » qui déborderait sur autrui serait le pire des défauts ici."""
    theirs = make_notification(tenant_a, client_aicha)
    make_notification(tenant_a, client_fatou)

    assert authenticated_client(client_fatou).post(MARK_ALL_URL).json() == {
        "marked_read": 1,
    }
    theirs.refresh_from_db()
    assert theirs.read_at is None
