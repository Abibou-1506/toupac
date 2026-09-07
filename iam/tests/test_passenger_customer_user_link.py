"""
TOUPAC IAM — Rattachement d'une fiche passager à un compte client.

Le passager reste une fiche propre à la compagnie : c'est celui qui embarque.
`customer_user` n'est qu'un pont facultatif vers le compte TOUPAC de cette
personne, quand elle en a un. Sans ce pont, la fiche est un « invité » — le cas
de qui réserve pour un proche.
"""
import pytest
from django.core.management import call_command

from iam.models import User
from voyage.models import Passenger

pytestmark = pytest.mark.django_db


def passenger_admin_form(user):
    """Classe de formulaire d'ajout de PassengerAdmin, telle que la verrait `user`."""
    from django.contrib import admin as django_admin
    from django.test import RequestFactory

    request = RequestFactory().get("/admin/voyage/passenger/add/")
    request.user = user
    return django_admin.site._registry[Passenger].get_form(request)


def make_passenger(tenant, **overrides):
    payload = {
        "tenant": tenant, "first_name": "Awa", "last_name": "Diop",
        "phone": "+221770000055", "nationality": "SN",
    }
    return Passenger.objects.create(**{**payload, **overrides})


def test_passenger_can_be_created_without_customer_user(tenant_a):
    """Le cas invité : on voyage souvent pour quelqu'un qui n'a pas de compte."""
    passenger = make_passenger(tenant_a)

    assert passenger.customer_user is None
    assert passenger.full_name == "Awa Diop"


def test_passenger_can_be_linked_to_a_client(tenant_a, client_fatou):
    passenger = make_passenger(tenant_a, customer_user=client_fatou)

    passenger.refresh_from_db()
    assert passenger.customer_user == client_fatou
    assert list(client_fatou.passenger_records.all()) == [passenger]


def test_one_client_holds_a_passenger_record_per_company(tenant_a, tenant_b, client_fatou):
    """
    Une fiche par compagnie, un seul compte.

    C'est ce qui rend la vue transverse possible sans fusionner les référentiels
    des compagnies, qui restent cloisonnés.
    """
    make_passenger(tenant_a, customer_user=client_fatou)
    make_passenger(tenant_b, customer_user=client_fatou)

    assert client_fatou.passenger_records.count() == 2
    assert set(client_fatou.passenger_records.values_list("tenant__slug", flat=True)) == {
        tenant_a.slug, tenant_b.slug,
    }


def test_field_is_limited_to_client_accounts():
    """`limit_choices_to` restreint le menu déroulant de l'admin aux clients."""
    field = Passenger._meta.get_field("customer_user")

    assert field.null is True
    assert field.blank is True
    assert field.get_limit_choices_to() == {"role": "client"}


def test_admin_form_rejects_a_staff_account(tenant_a, user_admin_a):
    """
    Le formulaire refuse un compte d'exploitation.

    `limit_choices_to` n'est pas décoratif : Django l'applique à la validation
    du champ, pas seulement à l'affichage des choix.
    """
    form_class = passenger_admin_form(user_admin_a)
    form = form_class(data={
        "tenant": str(tenant_a.pk), "first_name": "Awa", "last_name": "Diop",
        "customer_user": str(user_admin_a.pk), "nationality": "SN",
    })

    assert not form.is_valid()
    assert "customer_user" in form.errors


def test_admin_form_accepts_a_client_account(tenant_a, superadmin, client_fatou):
    form_class = passenger_admin_form(superadmin)
    form = form_class(data={
        "tenant": str(tenant_a.pk), "first_name": "Fatou", "last_name": "Mbaye",
        "customer_user": str(client_fatou.pk), "nationality": "SN",
    })

    assert form.is_valid(), form.errors


def test_deleting_the_client_keeps_the_passenger_record(tenant_a, client_fatou):
    """
    `SET_NULL` : effacer un compte ne fait pas disparaître le billet.

    Le passager reste une pièce d'exploitation pour la compagnie — la liste
    d'embarquement d'un voyage passé ne doit pas se vider parce qu'un client a
    fermé son compte.
    """
    passenger = make_passenger(tenant_a, customer_user=client_fatou)

    client_fatou.delete()

    passenger.refresh_from_db()
    assert passenger.pk is not None
    assert passenger.customer_user is None
    assert passenger.full_name == "Awa Diop"


def test_seed_demo_links_clients_across_both_companies():
    """
    Le jeu de démo produit bien un cas transverse.

    Vérifié sur une base neuve : sur une base déjà seedée, l'idempotence
    empêche le rattrapage — les fiches passager existent déjà sans compte.
    """
    for family in ("tenants", "places", "users", "fleet", "voyage"):
        call_command("seed_demo", only=family, quiet=True)

    linked = Passenger.objects.filter(customer_user__isnull=False)

    assert linked.exists(), "aucune fiche passager rattachée à un compte client"
    clients_with_two_companies = [
        client for client in User.objects.filter(role=User.Role.CLIENT)
        if client.passenger_records.values("tenant").distinct().count() >= 2
    ]
    assert clients_with_two_companies, "aucun client présent chez deux compagnies"
