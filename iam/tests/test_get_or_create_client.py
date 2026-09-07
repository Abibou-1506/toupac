"""
TOUPAC IAM — `User.get_or_create_client()`.

Le helper est le point d'entrée unique de création d'un passager : chatbot web,
chatbot WhatsApp, future app mobile. Sa propriété centrale est la convergence —
un même humain qui se présente tantôt par e-mail, tantôt par téléphone, doit
finir avec un seul compte et un seul historique.
"""
import pytest

from iam.models import User

pytestmark = pytest.mark.django_db


def test_creates_new_client_with_email_only():
    user, created = User.get_or_create_client(email="fatou@example.sn")

    assert created is True
    assert user.role == User.Role.CLIENT
    assert user.tenant is None
    assert user.email == "fatou@example.sn"
    assert user.phone == ""
    assert user.has_usable_password() is False
    assert user.is_staff is False
    assert user.is_superuser is False


def test_creates_new_client_with_phone_only():
    user, created = User.get_or_create_client(phone="+221770000001")

    assert created is True
    assert user.tenant is None
    assert user.phone == "+221770000001"
    # None et non "" : la colonne est unique, deux chaînes vides se heurteraient.
    assert user.email is None


def test_returns_existing_client_by_email():
    first, _ = User.get_or_create_client(email="fatou@example.sn", first_name="Fatou")

    second, created = User.get_or_create_client(email="fatou@example.sn")

    assert created is False
    assert second.pk == first.pk
    assert User.objects.filter(role=User.Role.CLIENT).count() == 1


def test_returns_existing_client_by_phone_when_email_is_new():
    """
    Le chatbot WhatsApp rejoint le compte ouvert par le chatbot web.

    C'est la convergence recherchée : le téléphone identifie la personne même
    quand l'e-mail présenté n'a jamais été vu.
    """
    first, _ = User.get_or_create_client(phone="+221770000001", first_name="Fatou")

    second, created = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
    )

    assert created is False
    assert second.pk == first.pk
    assert second.email == "fatou@example.sn"  # l'e-mail manquant est comblé


def test_email_takes_precedence_over_phone_for_resolution():
    """
    Deux comptes distincts, l'e-mail tranche — c'est l'identifiant le plus fort.

    Et le téléphone du second compte n'est pas recopié sur le premier : les
    fusionner exigerait de prouver que c'est bien la même personne, ce qu'un
    helper ne peut pas faire. Les comptes restent séparés.
    """
    by_email, _ = User.get_or_create_client(email="fatou@example.sn")
    by_phone, _ = User.get_or_create_client(phone="+221770000001")
    assert by_email.pk != by_phone.pk

    found, created = User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
    )

    assert created is False
    assert found.pk == by_email.pk
    found.refresh_from_db()
    assert found.phone == ""  # le numéro de l'autre compte n'a pas été volé
    by_phone.refresh_from_db()
    assert by_phone.phone == "+221770000001"


def test_enriches_existing_client_missing_fields():
    user, _ = User.get_or_create_client(email="fatou@example.sn")
    assert user.first_name == ""

    User.get_or_create_client(
        email="fatou@example.sn", phone="+221770000001",
        first_name="Fatou", last_name="Mbaye",
    )

    user.refresh_from_db()
    assert user.first_name == "Fatou"
    assert user.last_name == "Mbaye"
    assert user.phone == "+221770000001"


def test_never_overwrites_an_existing_value():
    """
    L'enrichissement comble, il ne remplace pas.

    Écraser l'e-mail d'un compte existant depuis un appel entrant reviendrait à
    offrir une prise de contrôle de compte à qui devine un numéro.
    """
    user, _ = User.get_or_create_client(
        email="vrai@example.sn", phone="+221770000001", first_name="Fatou",
    )

    User.get_or_create_client(
        phone="+221770000001", email="pirate@example.sn", first_name="Pirate",
    )

    user.refresh_from_db()
    assert user.email == "vrai@example.sn"
    assert user.first_name == "Fatou"


def test_raises_when_no_email_no_phone():
    with pytest.raises(ValueError, match="au moins un email ou un téléphone"):
        User.get_or_create_client()


def test_empty_strings_are_treated_as_absent():
    with pytest.raises(ValueError):
        User.get_or_create_client(email="", phone="")


def test_does_not_match_a_staff_user_sharing_the_email(tenant_a):
    """
    Un compte d'exploitation ne doit jamais être requalifié en client.

    La recherche est filtrée sur `role=CLIENT` : sans ce filtre, un agent qui
    réserve un billet avec son e-mail professionnel verrait son compte staff
    renvoyé, puis enrichi comme un compte client.
    """
    staff = User.objects.create_user(
        email="agent@sahel.sn", password="TestPass#2026", first_name="Awa",
        last_name="Ndiaye", tenant=tenant_a, role=User.Role.AGENT,
    )

    with pytest.raises(ValueError, match="déjà utilisé"):
        User.get_or_create_client(email="agent@sahel.sn")

    staff.refresh_from_db()
    assert staff.role == User.Role.AGENT
    assert staff.tenant == tenant_a
    assert User.objects.filter(role=User.Role.CLIENT).count() == 0


def test_is_idempotent_across_many_calls():
    for _ in range(3):
        User.get_or_create_client(
            email="fatou@example.sn", phone="+221770000001", first_name="Fatou",
        )

    assert User.objects.filter(role=User.Role.CLIENT).count() == 1
