"""
TOUPAC IAM — Doctrine rôle/tenant : validation Django et contraintes de base.

Les deux niveaux sont testés séparément parce qu'ils ne servent pas à la même
chose. `User.clean()` produit un message lisible dans un formulaire ; les
contraintes de base tiennent quand `clean()` n'est pas appelé — `bulk_create`,
`update()`, SQL direct, migration de données.
"""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from iam.models import User

pytestmark = pytest.mark.django_db

STAFF_ROLES = [
    User.Role.ADMIN, User.Role.DISPATCHER, User.Role.AGENT,
    User.Role.DRIVER, User.Role.CONTROLLER,
]


def _user(**overrides):
    """Instance non sauvegardée, avec des valeurs par défaut valides."""
    defaults = {
        "email": "someone@example.sn", "phone": "", "first_name": "A", "last_name": "B",
        "role": User.Role.AGENT, "tenant": None,
    }
    return User(**{**defaults, **overrides})


# ─── User.clean() ───

def test_client_cannot_have_tenant(tenant_a):
    with pytest.raises(ValidationError) as excinfo:
        _user(role=User.Role.CLIENT, tenant=tenant_a).clean()

    assert "tenant" in excinfo.value.message_dict


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_staff_role_requires_tenant(role):
    with pytest.raises(ValidationError) as excinfo:
        _user(role=role, tenant=None).clean()

    assert "tenant" in excinfo.value.message_dict


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_staff_role_accepts_tenant(role, tenant_a):
    _user(role=role, tenant=tenant_a).clean()  # ne lève pas


def test_superadmin_cannot_have_tenant(tenant_a):
    with pytest.raises(ValidationError) as excinfo:
        _user(role=User.Role.SUPERADMIN, tenant=tenant_a).clean()

    assert "tenant" in excinfo.value.message_dict


def test_superadmin_without_tenant_is_valid():
    _user(role=User.Role.SUPERADMIN, tenant=None).clean()


def test_client_must_have_email_or_phone():
    with pytest.raises(ValidationError) as excinfo:
        _user(role=User.Role.CLIENT, tenant=None, email=None, phone="").clean()

    assert "email" in excinfo.value.message_dict


def test_client_with_phone_only_is_valid():
    _user(role=User.Role.CLIENT, tenant=None, email=None, phone="+221770000001").clean()


def test_service_account_accepts_both_tenant_states(tenant_a):
    """Les deux cas sont légitimes : bot de compagnie et platform-bot global."""
    _user(role=User.Role.SERVICE_ACCOUNT, tenant=tenant_a).clean()
    _user(role=User.Role.SERVICE_ACCOUNT, tenant=None).clean()


# ─── Contraintes de base (clean() contourné) ───

def _force_create(**overrides):
    """Écrit en base sans passer par `clean()`, comme le ferait du code oublieux."""
    User.objects.bulk_create([_user(**overrides)])


def test_db_constraint_rejects_client_with_tenant(tenant_a):
    with pytest.raises(IntegrityError, match="user_tenant_matches_role"), transaction.atomic():
        _force_create(role=User.Role.CLIENT, tenant=tenant_a, email="c@example.sn")


def test_db_constraint_rejects_staff_without_tenant():
    with pytest.raises(IntegrityError, match="user_tenant_matches_role"), transaction.atomic():
        _force_create(role=User.Role.DRIVER, tenant=None, email="d@example.sn")


def test_db_constraint_rejects_superadmin_with_tenant(tenant_a):
    with pytest.raises(IntegrityError, match="user_tenant_matches_role"), transaction.atomic():
        _force_create(role=User.Role.SUPERADMIN, tenant=tenant_a, email="s@example.sn")


def test_db_constraint_rejects_client_without_contact():
    with pytest.raises(IntegrityError, match="user_client_has_contact"), transaction.atomic():
        _force_create(role=User.Role.CLIENT, tenant=None, email=None, phone="")


def test_db_constraint_rejects_two_clients_sharing_a_phone():
    User.get_or_create_client(phone="+221770000001")

    with pytest.raises(IntegrityError, match="user_client_phone_unique"), transaction.atomic():
        _force_create(
            role=User.Role.CLIENT, tenant=None, email="autre@example.sn",
            phone="+221770000001",
        )


def test_client_and_driver_may_share_a_phone(tenant_a):
    """Le chauffeur qui voyage aussi comme passager, c'est le même numéro."""
    shared = "+221770000001"
    User.get_or_create_client(phone=shared, first_name="Moussa")

    driver = User.objects.create_user(
        email="moussa@sahel.sn", password="TestPass#2026", first_name="Moussa",
        last_name="Diallo", tenant=tenant_a, role=User.Role.DRIVER, phone=shared,
    )

    assert driver.pk is not None
    assert User.objects.filter(phone=shared).count() == 2


def test_multiple_clients_may_have_no_email():
    """Deux NULL ne se heurtent pas dans un index unique PostgreSQL."""
    User.get_or_create_client(phone="+221770000001")
    User.get_or_create_client(phone="+221770000002")

    assert User.objects.filter(role=User.Role.CLIENT, email__isnull=True).count() == 2


def test_email_remains_unique_when_set():
    User.get_or_create_client(email="doublon@example.sn")

    with pytest.raises(IntegrityError), transaction.atomic():
        _force_create(role=User.Role.CLIENT, tenant=None, email="doublon@example.sn")


def test_guardian_anonymous_user_satisfies_the_constraints():
    """
    django-guardian recrée « AnonymousUser » à chaque post_migrate.

    Sa fabrique par défaut le laisse en rôle `agent` sans tenant, ce que
    `user_tenant_matches_role` interdit : sans la fabrique d'iam/guardian.py,
    `migrate` échouerait sur toute base neuve — celle-ci comprise.
    """
    anonymous = User.objects.get(email="AnonymousUser")

    assert anonymous.role == User.Role.SERVICE_ACCOUNT
    assert anonymous.tenant is None
