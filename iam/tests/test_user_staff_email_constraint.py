"""
TOUPAC IAM — Le personnel doit avoir un e-mail.

Depuis USR-1 l'e-mail est facultatif sur le modèle, pour que le client puisse
n'avoir qu'un téléphone. Cette liberté ne vaut pas pour le personnel : sans
adresse, le compte existe mais personne ne pourra jamais s'y connecter, puisque
la connexion par mot de passe passe par `USERNAME_FIELD = "email"`.
"""
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from iam.models import User

pytestmark = pytest.mark.django_db

STAFF_ROLES = [
    User.Role.ADMIN, User.Role.DISPATCHER, User.Role.AGENT,
    User.Role.DRIVER, User.Role.CONTROLLER,
]


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_clean_refuses_staff_without_email(role, tenant_a):
    user = User(
        email=None, phone="+221770000001", first_name="A", last_name="B",
        role=role, tenant=tenant_a,
    )

    with pytest.raises(ValidationError) as excinfo:
        user.clean()

    assert "email" in excinfo.value.message_dict


def test_clean_refuses_superadmin_without_email():
    user = User(email=None, first_name="A", last_name="B",
                role=User.Role.SUPERADMIN, tenant=None)

    with pytest.raises(ValidationError) as excinfo:
        user.clean()

    assert "email" in excinfo.value.message_dict


def test_clean_accepts_staff_with_email(tenant_a):
    User(
        email="agent@sahel.sn", first_name="A", last_name="B",
        role=User.Role.AGENT, tenant=tenant_a,
    ).clean()  # ne lève pas


def test_clean_still_allows_a_client_without_email():
    """La règle ne déborde pas sur le client, qui se connecte par code."""
    User(
        email=None, phone="+221770000001", first_name="A", last_name="B",
        role=User.Role.CLIENT, tenant=None,
    ).clean()


def test_clean_still_allows_a_service_account_without_email(tenant_a):
    """Un compte de service ne se connecte jamais : rien ne l'oblige."""
    User(
        email=None, first_name="A", last_name="B",
        role=User.Role.SERVICE_ACCOUNT, tenant=tenant_a,
    ).clean()


def test_db_constraint_refuses_staff_without_email(tenant_a):
    """Le filet tient quand `clean()` n'est pas appelé — ici en SQL direct."""
    sql = (
        "INSERT INTO iam_users "
        "(id, password, is_superuser, email, phone, first_name, last_name, role, "
        " is_active, is_staff, created_at, updated_at, notification_preferences, tenant_id) "
        "VALUES (%s, 'x', false, NULL, '', 'A', 'B', 'agent', true, false, "
        " now(), now(), '{}', %s)"
    )

    with pytest.raises(IntegrityError, match="user_staff_has_email"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sql, [str(uuid.uuid4()), str(tenant_a.id)])


def test_db_constraint_allows_client_without_email():
    """La même insertion, en rôle client, passe."""
    User.objects.bulk_create([
        User(
            email=None, phone="+221770000001", first_name="A", last_name="B",
            role=User.Role.CLIENT, tenant=None,
        ),
    ])

    assert User.objects.filter(role=User.Role.CLIENT, email__isnull=True).count() == 1


def test_all_seeded_staff_have_an_email():
    """
    Aucun membre du personnel sans adresse ne subsiste après migration.

    La contrainte l'interdit désormais ; ce test vérifie que la base de test —
    construite par le jeu complet des migrations, guardian compris — la respecte
    réellement, plutôt que de le supposer.
    """
    orphans = User.objects.filter(
        role__in=[*STAFF_ROLES, User.Role.SUPERADMIN], email__isnull=True,
    )

    assert list(orphans) == []
