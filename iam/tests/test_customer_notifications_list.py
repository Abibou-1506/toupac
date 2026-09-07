"""
TOUPAC IAM — Le centre d'alertes du client : liste, filtres, isolation.

Une notification appartient à une personne, pas à une compagnie. C'est ce qui
distingue ces vues du reste du projet, et ce que le premier test vérifie : deux
clients ne se voient jamais, sans qu'aucun filtre de compagnie n'intervienne.
"""
import pytest

from iam.models import User
from iam.tests.customer_factories import (
    EVENT_PAYMENT,
    EVENT_TICKET,
    EVENT_TRIP_DELAYED,
    make_notification,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/customer/notifications/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def test_the_list_is_paginated_and_names_its_collection(
    authenticated_client, client_fatou, tenant_a,
):
    """La forme suit celle des autres endpoints client : la collection est nommée."""
    for _ in range(3):
        make_notification(tenant_a, client_fatou)

    body = authenticated_client(client_fatou).get(URL).json()

    assert body["count"] == 3
    assert len(body["notifications"]) == 3
    assert body["next"] is None
    assert body["previous"] is None


def test_a_client_without_notifications_gets_an_empty_list(
    authenticated_client, client_fatou,
):
    body = authenticated_client(client_fatou).get(URL).json()

    assert body["count"] == 0
    assert body["notifications"] == []


def test_the_newest_alert_comes_first(authenticated_client, client_fatou, tenant_a):
    make_notification(tenant_a, client_fatou, title="Ancienne")
    make_notification(tenant_a, client_fatou, title="Récente")

    titles = [
        item["title"]
        for item in authenticated_client(client_fatou).get(URL).json()["notifications"]
    ]

    assert titles == ["Récente", "Ancienne"]


def test_two_clients_never_see_each_other(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    """
    L'isolation ne passe par aucune compagnie.

    Les deux notifications appartiennent au même transporteur : seul le
    destinataire les sépare.
    """
    make_notification(tenant_a, client_fatou, title="Pour Fatou")
    make_notification(tenant_a, client_aicha, title="Pour Aïcha")

    body = authenticated_client(client_fatou).get(URL).json()

    assert body["count"] == 1
    assert body["notifications"][0]["title"] == "Pour Fatou"


def test_the_alerts_of_several_companies_are_gathered(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    """C'est l'intérêt d'un centre d'alertes : un seul endroit pour tout."""
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_b, client_fatou)

    body = authenticated_client(client_fatou).get(URL).json()

    assert body["count"] == 2
    assert {item["tenant_slug"] for item in body["notifications"]} == {
        tenant_a.slug, tenant_b.slug,
    }


# ─── Les filtres ───

def test_unread_keeps_only_what_has_not_been_read(
    authenticated_client, client_fatou, tenant_a,
):
    from django.utils import timezone

    make_notification(tenant_a, client_fatou, title="Non lue")
    make_notification(tenant_a, client_fatou, title="Lue", read_at=timezone.now())

    body = authenticated_client(client_fatou).get(URL, {"unread": "true"}).json()

    assert body["count"] == 1
    assert body["notifications"][0]["title"] == "Non lue"


def test_the_tenant_filter_keeps_one_company(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    make_notification(tenant_a, client_fatou)
    make_notification(tenant_b, client_fatou)

    body = authenticated_client(client_fatou).get(URL, {"tenant": tenant_a.slug}).json()

    assert body["count"] == 1
    assert body["notifications"][0]["tenant_slug"] == tenant_a.slug


def test_the_category_filter_spans_several_event_codes(
    authenticated_client, client_fatou, tenant_a,
):
    """
    La catégorie n'est pas stockée : elle est lue sur l'événement.

    Deux codes distincts de la même catégorie doivent donc ressortir ensemble,
    et un code d'une autre catégorie rester dehors. Un test sur un seul code ne
    distinguerait pas ce filtre d'un filtre sur `event_code`.
    """
    make_notification(tenant_a, client_fatou, event_code=EVENT_TICKET)
    make_notification(tenant_a, client_fatou, event_code=EVENT_TRIP_DELAYED)
    make_notification(tenant_a, client_fatou, event_code=EVENT_PAYMENT)

    body = authenticated_client(client_fatou).get(
        URL, {"category": "trip_updates"},
    ).json()

    assert body["count"] == 2
    assert {item["event_code"] for item in body["notifications"]} == {
        EVENT_TICKET, EVENT_TRIP_DELAYED,
    }
    assert all(item["category"] == "trip_updates" for item in body["notifications"])


def test_an_unknown_category_returns_nothing(authenticated_client, client_fatou, tenant_a):
    make_notification(tenant_a, client_fatou)

    body = authenticated_client(client_fatou).get(URL, {"category": "inexistante"}).json()

    assert body["count"] == 0


def test_the_priority_filter_keeps_one_level(authenticated_client, client_fatou, tenant_a):
    make_notification(tenant_a, client_fatou, priority="critical", title="Critique")
    make_notification(tenant_a, client_fatou, priority="low", title="Basse")

    body = authenticated_client(client_fatou).get(URL, {"priority": "critical"}).json()

    assert body["count"] == 1
    assert body["notifications"][0]["title"] == "Critique"


def test_filters_combine(authenticated_client, client_fatou, tenant_a, tenant_b):
    from django.utils import timezone

    make_notification(tenant_a, client_fatou, title="Cherchée")
    make_notification(tenant_a, client_fatou, read_at=timezone.now())
    make_notification(tenant_b, client_fatou)

    body = authenticated_client(client_fatou).get(
        URL, {"unread": "true", "tenant": tenant_a.slug},
    ).json()

    assert body["count"] == 1
    assert body["notifications"][0]["title"] == "Cherchée"


# ─── La pagination ───

def test_a_second_page_is_announced(authenticated_client, client_fatou, tenant_a):
    for _ in range(3):
        make_notification(tenant_a, client_fatou)

    body = authenticated_client(client_fatou).get(URL, {"page_size": 2}).json()

    assert body["count"] == 3
    assert len(body["notifications"]) == 2
    assert body["next"] is not None


def test_a_page_size_above_the_ceiling_is_refused(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Refusé plutôt que ramené en silence au plafond.

    Un client qui demande cent éléments et en reçoit cinquante sans le savoir
    croira la liste terminée et perdra la moitié des alertes.
    """
    make_notification(tenant_a, client_fatou)

    response = authenticated_client(client_fatou).get(URL, {"page_size": 100})

    assert response.status_code == 400
    assert "page_size" in response.json()


def test_a_nonsense_page_size_is_refused(authenticated_client, client_fatou):
    response = authenticated_client(client_fatou).get(URL, {"page_size": "beaucoup"})

    assert response.status_code == 400


# ─── Le contrat exposé ───

EXPECTED_FIELDS = {
    "id", "tenant_slug", "tenant_name", "event_code", "category", "priority",
    "title", "body", "action_url", "read_at", "acked_at", "requires_ack",
    "created_at",
}

INTERNAL_FIELDS = {"trigger_scope", "trigger_role", "idempotency_key", "expires_at"}


def test_the_serializer_exposes_exactly_the_whitelist(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Égalité stricte, pas une inclusion.

    Un champ ajouté plus tard au modèle deviendrait un contrat public sans que
    personne ne l'ait décidé ; l'égalité transforme cet ajout en test rouge.
    """
    make_notification(tenant_a, client_fatou)

    item = authenticated_client(client_fatou).get(URL).json()["notifications"][0]

    assert set(item) == EXPECTED_FIELDS
    assert not INTERNAL_FIELDS & set(item)


def test_the_derived_fields_come_from_the_catalog(
    authenticated_client, client_fatou, tenant_a,
):
    make_notification(tenant_a, client_fatou, event_code=EVENT_TICKET)

    item = authenticated_client(client_fatou).get(URL).json()["notifications"][0]

    assert item["category"] == "trip_updates"
    assert item["requires_ack"] is False


def test_a_code_retired_from_the_catalog_does_not_break_the_list(
    authenticated_client, client_fatou, tenant_a,
):
    """
    Une ligne écrite sous un code depuis retiré reste lisible.

    Lever ici rendrait tout le centre d'alertes inaccessible pour une seule
    ligne périmée — et un code retiré du catalogue laisse forcément des lignes.
    """
    make_notification(tenant_a, client_fatou, event_code="notif.disparu.v1")

    item = authenticated_client(client_fatou).get(URL).json()["notifications"][0]

    assert item["category"] == ""
    assert item["requires_ack"] is False


def test_the_body_is_returned_in_full(authenticated_client, client_fatou, tenant_a):
    """
    Aucun masque de confidentialité ici.

    Les masques (N-05) portent sur le rendu poussé, qui s'affiche sur un écran
    verrouillé. Le destinataire s'est authentifié pour lire ce qui lui revient.
    """
    make_notification(
        tenant_a, client_fatou, body="Votre billet REF-001 — QR : SECRET-QR",
    )

    item = authenticated_client(client_fatou).get(URL).json()["notifications"][0]

    assert item["body"] == "Votre billet REF-001 — QR : SECRET-QR"
    assert "***" not in item["body"]
