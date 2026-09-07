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
