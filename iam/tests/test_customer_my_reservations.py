"""
TOUPAC IAM — `/customer/my-reservations/`, la vue transverse du voyageur.

Le lien passe par la fiche passager. Ce que ces tests verrouillent surtout,
c'est l'isolation : un client ne voit que les billets où il est nommément le
voyageur, chez toutes les compagnies et seulement chez elles.
"""
from datetime import date, timedelta

import pytest

from iam.models import User
from iam.tests.customer_factories import make_reservation, make_trip
from voyage.models import Reservation

pytestmark = pytest.mark.django_db

URL = "/api/v1/customer/my-reservations/"


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


def get(authenticated_client, user, query=""):
    return authenticated_client(user).get(f"{URL}{query}")


def test_returns_empty_when_no_reservations(authenticated_client, client_fatou):
    response = get(authenticated_client, client_fatou)

    assert response.status_code == 200
    assert response.json()["reservations"] == []


def test_returns_client_reservations_cross_tenant(
    authenticated_client, client_fatou, tenant_a, tenant_b,
):
    make_reservation(tenant_a, customer_user=client_fatou)
    make_reservation(tenant_b, customer_user=client_fatou)

    items = get(authenticated_client, client_fatou).json()["reservations"]

    assert len(items) == 2
    assert {item["tenant_slug"] for item in items} == {tenant_a.slug, tenant_b.slug}
    # Sans le nom de la compagnie, un billet transverse est inexploitable.
    assert all(item["tenant_name"] for item in items)


def test_isolation_between_clients(
    authenticated_client, client_fatou, client_aicha, tenant_a,
):
    mine = make_reservation(tenant_a, customer_user=client_fatou)
    make_reservation(tenant_a, customer_user=client_aicha)

    items = get(authenticated_client, client_fatou).json()["reservations"]

    assert [item["id"] for item in items] == [str(mine.id)]


def test_guest_passenger_belongs_to_nobody(authenticated_client, client_fatou, tenant_a):
    """Une fiche sans compte ne remonte chez personne."""
    make_reservation(tenant_a, customer_user=None)

    assert get(authenticated_client, client_fatou).json()["reservations"] == []


def test_tenant_filter_works(authenticated_client, client_fatou, tenant_a, tenant_b):
    make_reservation(tenant_a, customer_user=client_fatou)
    make_reservation(tenant_b, customer_user=client_fatou)

    items = get(authenticated_client, client_fatou, f"?tenant={tenant_a.slug}").json()["reservations"]

    assert len(items) == 1
    assert items[0]["tenant_slug"] == tenant_a.slug


def test_upcoming_filter_excludes_past(authenticated_client, client_fatou, tenant_a):
    past = make_trip(tenant_a, departure_date=date.today() - timedelta(days=30))
    future = make_trip(tenant_a, departure_date=date.today() + timedelta(days=30))
    make_reservation(tenant_a, customer_user=client_fatou, trip=past)
    upcoming = make_reservation(tenant_a, customer_user=client_fatou, trip=future)

    items = get(authenticated_client, client_fatou, "?upcoming=true").json()["reservations"]

    assert [item["id"] for item in items] == [str(upcoming.id)]


def test_upcoming_includes_today(authenticated_client, client_fatou, tenant_a):
    """Un départ du jour est encore à venir — il ne doit pas disparaître."""
    today = make_trip(tenant_a, departure_date=date.today())
    make_reservation(tenant_a, customer_user=client_fatou, trip=today)

    assert len(get(authenticated_client, client_fatou, "?upcoming=true").json()["reservations"]) == 1


def test_status_filter_works(authenticated_client, client_fatou, tenant_a):
    make_reservation(tenant_a, customer_user=client_fatou, status=Reservation.Status.BOOKED)
    cancelled = make_reservation(
        tenant_a, customer_user=client_fatou, status=Reservation.Status.CANCELLED,
    )

    items = get(authenticated_client, client_fatou, "?status=cancelled").json()["reservations"]

    assert [item["id"] for item in items] == [str(cancelled.id)]


def test_soft_deleted_passenger_disappears(authenticated_client, client_fatou, tenant_a):
    """Effacement RGPD : la fiche effacée ne remonte plus dans l'historique."""
    reservation = make_reservation(tenant_a, customer_user=client_fatou)
    reservation.passenger.soft_delete()

    assert get(authenticated_client, client_fatou).json()["reservations"] == []


def test_serializer_does_not_leak_internal_fields(
    authenticated_client, client_fatou, tenant_a, user_admin_a,
):
    """
    Les colonnes d'exploitation appartiennent à la compagnie, pas au voyageur.

    `qr_code_jwt` est le plus sensible : ce jeton vaut le billet lui-même.
    """
    make_reservation(
        tenant_a, customer_user=client_fatou,
        created_by=user_admin_a, qr_code_jwt="jeton-secret",
        refusal_reason="motif interne",
    )

    item = get(authenticated_client, client_fatou).json()["reservations"][0]

    for leaked in (
        "created_by", "boarded_by", "boarding_method", "qr_code_jwt",
        "refusal_reason", "special_case_reason", "payment_ref",
    ):
        assert leaked not in item
    assert "jeton-secret" not in str(item)
    assert "motif interne" not in str(item)


def test_exposes_the_expected_fields(authenticated_client, client_fatou, tenant_a):
    make_reservation(tenant_a, customer_user=client_fatou)

    item = get(authenticated_client, client_fatou).json()["reservations"][0]

    assert set(item) == {
        "id", "tenant_slug", "tenant_name", "trip_route_name", "trip_route_code",
        "trip_departure_date", "trip_scheduled_at", "seat_label", "status",
        "amount_xof", "passenger_full_name",
    }


def test_staff_is_refused(authenticated_client, user_admin_a):
    assert authenticated_client(user_admin_a).get(URL).status_code == 403


def test_anonymous_is_refused(api_client):
    assert api_client.get(URL).status_code == 401
