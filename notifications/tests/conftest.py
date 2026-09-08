"""Fixtures partagées par les tests du module notifications."""
import pytest

from iam.models import User


@pytest.fixture
def client_fatou():
    """Client TOUPAC : global, sans compagnie — le destinataire type."""
    user, _ = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
        first_name="Fatou", last_name="Mbaye",
    )
    return user


@pytest.fixture
def client_aicha():
    user, _ = User.get_or_create_client(
        email="aicha@example.sn", first_name="Aïcha", last_name="Sow",
    )
    return user


# ─── Décors métier des resolvers ───
#
# Un resolver part d'une entité — un voyage, un colis, un paiement — pour
# atteindre une personne. Monter cette entité demande une chaîne complète ;
# ces fixtures la montent une fois, pour que chaque test parle de la résolution
# qu'il vérifie et pas du décor qui l'entoure.

@pytest.fixture
def trip_with_two_passengers(tenant_a, client_fatou, client_aicha, user_driver_a):
    """
    Un voyage, deux voyageurs rattachés à leur compte, un chauffeur affecté.

    Rend un objet portant `trip`, `reservations`, `driver_user` — de quoi
    vérifier à la fois qui est trouvé et qui ne l'est pas.
    """
    from types import SimpleNamespace

    from fleet.models import Driver
    from iam.tests.customer_factories import make_reservation

    first = make_reservation(tenant_a, customer_user=client_fatou)
    second = make_reservation(
        tenant_a, customer_user=client_aicha, trip=first.trip,
    )
    driver = Driver.objects.create(
        tenant=tenant_a, user=user_driver_a, license_number="PC-001",
    )
    first.trip.driver = driver
    first.trip.save(update_fields=["driver"])

    return SimpleNamespace(
        trip=first.trip,
        reservations=[first, second],
        driver_user=user_driver_a,
        customers=[client_fatou, client_aicha],
    )


@pytest.fixture
def parcel_order(tenant_a, client_fatou, client_aicha):
    """Un colis expédié par Fatou à Aïcha — les deux ont un compte."""
    from iam.tests.customer_factories import make_order

    order = make_order(tenant_a, customer=client_fatou)
    order.recipient_user = client_aicha
    order.recipient_name = "Aïcha Sow"
    order.recipient_phone = "+221770000002"
    order.save(update_fields=["recipient_user", "recipient_name", "recipient_phone"])
    return order


@pytest.fixture
def payment_on_order(tenant_a, parcel_order):
    """Un paiement rattaché à une commande de colis — le chemin le plus direct."""
    from billing.models import Payment

    return Payment.objects.create(
        tenant=tenant_a, order=parcel_order, provider=Payment.Provider.WAVE,
        amount_xof=15000, status=Payment.Status.SUCCESS,
    )
