"""
TOUPAC IAM — Marquer lu, acquitter : deux gestes distincts.

Lire est passif — le centre d'alertes s'ouvre. Acquitter est volontaire — un
bouton est pressé. D'où l'asymétrie vérifiée ici : acquitter vaut lecture,
l'inverse jamais.
"""
import pytest

from iam.models import User
from iam.tests.customer_factories import (
    EVENT_NEEDS_ACK,
    EVENT_TICKET,
    make_notification,
)

pytestmark = pytest.mark.django_db


def read_url(notification):
    return f"/api/v1/customer/notifications/{notification.id}/read/"


def ack_url(notification):
    return f"/api/v1/customer/notifications/{notification.id}/ack/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


# ─── Marquer lu ───

def test_marking_read_stamps_the_date(authenticated_client, client_fatou, tenant_a):
    notification = make_notification(tenant_a, client_fatou)

    response = authenticated_client(client_fatou).post(read_url(notification))

    assert response.status_code == 200
    assert response.json()["read_at"] is not None
    notification.refresh_from_db()
    assert notification.read_at is not None


def test_marking_read_twice_does_not_move_the_date(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Idempotent : la date garde le sens de « première consultation ».

    Sans cela, un client qui rouvre son centre d'alertes devrait vérifier l'état
    avant d'appeler, et la date ne dirait plus rien.
    """
    notification = make_notification(tenant_a, client_fatou)
    api = authenticated_client(client_fatou)

    first = api.post(read_url(notification)).json()["read_at"]
    second = api.post(read_url(notification))

    assert second.status_code == 200
    assert second.json()["read_at"] == first


def test_marking_read_does_not_acknowledge(authenticated_client, client_fatou, tenant_a):
    """Lire n'est pas acquitter — c'est tout le point d'avoir deux champs."""
    notification = make_notification(tenant_a, client_fatou)

    body = authenticated_client(client_fatou).post(read_url(notification)).json()

    assert body["read_at"] is not None
    assert body["acked_at"] is None


def test_marking_read_someone_elses_alert_is_not_found(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """
    404 et non 403 : un 403 confirmerait que la notification existe.

    L'identifiant suffirait alors à sonder le système.
    """
    notification = make_notification(tenant_a, client_aicha)

    response = authenticated_client(client_fatou).post(read_url(notification))

    assert response.status_code == 404
    notification.refresh_from_db()
    assert notification.read_at is None


def test_marking_read_an_unknown_identifier_is_not_found(
    authenticated_client, client_fatou,
):
    import uuid

    response = authenticated_client(client_fatou).post(
        f"/api/v1/customer/notifications/{uuid.uuid4()}/read/",
    )

    assert response.status_code == 404


# ─── Acquitter ───

def test_acknowledging_stamps_both_dates(authenticated_client, client_fatou, tenant_a):
    """Acquitter vaut lecture : presser le bouton, c'est avoir vu."""
    notification = make_notification(tenant_a, client_fatou, event_code=EVENT_NEEDS_ACK)

    body = authenticated_client(client_fatou).post(ack_url(notification)).json()

    assert body["acked_at"] is not None
    assert body["read_at"] is not None
    assert body["requires_ack"] is True


def test_acknowledging_preserves_an_earlier_read_date(
    authenticated_client, client_fatou, tenant_a,
):
    """La première consultation reste datée pour ce qu'elle était."""
    from datetime import timedelta

    from django.utils import timezone

    earlier = timezone.now() - timedelta(hours=2)
    notification = make_notification(
        tenant_a, client_fatou, event_code=EVENT_NEEDS_ACK, read_at=earlier,
    )

    body = authenticated_client(client_fatou).post(ack_url(notification)).json()

    notification.refresh_from_db()
    assert notification.read_at == earlier
    assert body["acked_at"] is not None


def test_acknowledging_twice_does_not_move_the_date(
    authenticated_client, client_fatou, tenant_a,
):
    notification = make_notification(tenant_a, client_fatou, event_code=EVENT_NEEDS_ACK)
    api = authenticated_client(client_fatou)

    first = api.post(ack_url(notification)).json()["acked_at"]
    second = api.post(ack_url(notification))

    assert second.status_code == 200
    assert second.json()["acked_at"] == first


def test_acknowledging_an_event_that_asks_for_none_is_refused(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Sinon la date ne voudrait plus rien dire.

    L'interface ne propose aucun bouton pour ces événements : une date
    d'acquittement y serait une trace dont personne ne saurait l'origine.
    """
    notification = make_notification(tenant_a, client_fatou, event_code=EVENT_TICKET)

    response = authenticated_client(client_fatou).post(ack_url(notification))

    assert response.status_code == 400
    assert "accusé de réception" in response.json()["detail"]
    notification.refresh_from_db()
    assert notification.acked_at is None


def test_acknowledging_an_event_unknown_to_the_catalog_is_refused(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Le doute profite à l'abstention.

    Sans l'événement, rien ne dit si un acquittement était attendu — et la
    liste, elle, reste lisible : seul ce geste est refusé.
    """
    notification = make_notification(tenant_a, client_fatou, event_code="notif.disparu.v1")

    response = authenticated_client(client_fatou).post(ack_url(notification))

    assert response.status_code == 400
    assert "notif.disparu.v1" in response.json()["detail"]


def test_acknowledging_someone_elses_alert_is_not_found(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    notification = make_notification(
        tenant_a, client_aicha, event_code=EVENT_NEEDS_ACK,
    )

    response = authenticated_client(client_fatou).post(ack_url(notification))

    assert response.status_code == 404
    notification.refresh_from_db()
    assert notification.acked_at is None
