"""
TOUPAC IAM — Comptes de service portant les clés API.

Chaque tenant a un porteur technique, provisionné dès sa création. L'invariant
compte : sans lui, une clé n'aurait pour porteur qu'un salarié, dont le départ
rendrait orphelines — donc inutilisables — toutes les clés qu'il portait.
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.auth.models import Permission
from django.contrib.gis.geos import Point
from django.db.models.signals import post_save
from django.test import Client

from geo.models import Place
from iam.models import Tenant, User
from iam.signals import provision_service_account
from voyage.models import Route

pytestmark = pytest.mark.django_db

SIGNAL_UID = "iam.provision_service_account"


def bot_email(slug):
    return f"api-bot@{slug}.internal"


# ─── Provisionnement ───

def test_creating_tenant_creates_service_account():
    tenant = Tenant.objects.create(name="New Company", slug="new-tenant")

    bot = User.objects.get(email=bot_email("new-tenant"))

    assert bot.role == User.Role.SERVICE_ACCOUNT
    assert bot.tenant_id == tenant.id
    assert bot.first_name == "API" and bot.last_name == "Bot"
    assert bot.is_active is True
    assert bot.is_staff is False
    assert bot.is_superuser is False
    # Le compte ne peut pas se connecter : aucun mot de passe ne correspondra.
    assert bot.has_usable_password() is False


def test_service_account_has_no_django_permissions():
    """Le bot ne peut rien faire hors de ce que ses clés API autorisent."""
    tenant = Tenant.objects.create(name="Perm Check", slug="perm-check")
    bot = User.objects.get(email=bot_email(tenant.slug))

    assert bot.groups.count() == 0
    assert bot.user_permissions.count() == 0
    assert not bot.get_all_permissions()


def test_service_account_creation_is_idempotent():
    tenant = Tenant.objects.create(name="Idem", slug="idem")

    first = tenant.get_or_create_service_account()
    second = tenant.get_or_create_service_account()
    third = tenant.get_or_create_service_account()

    assert first.pk == second.pk == third.pk
    assert User.objects.filter(email=bot_email("idem")).count() == 1


def test_get_or_create_service_account_creates_missing_bot():
    """Auto-guérison : le helper recrée le porteur si quelqu'un l'a supprimé."""
    tenant = Tenant.objects.create(name="Healing", slug="healing")
    User.objects.filter(email=bot_email("healing")).delete()

    bot = tenant.get_or_create_service_account()

    assert bot.email == bot_email("healing")
    assert bot.has_usable_password() is False


def test_data_migration_backfills_existing_tenants():
    """
    Exécute la vraie fonction de la migration 0004, pas une copie.

    Le tenant est créé signal débranché, pour reproduire l'état d'une base
    antérieure au provisionnement automatique.
    """
    post_save.disconnect(sender=Tenant, dispatch_uid=SIGNAL_UID)
    try:
        Tenant.objects.create(name="Legacy", slug="legacy-tenant")
    finally:
        post_save.connect(provision_service_account, sender=Tenant, dispatch_uid=SIGNAL_UID)

    assert not User.objects.filter(email=bot_email("legacy-tenant")).exists()

    migration = importlib.import_module("iam.migrations.0004_backfill_service_accounts")
    migration.backfill_service_accounts(django_apps, None)

    bot = User.objects.get(email=bot_email("legacy-tenant"))
    assert bot.role == User.Role.SERVICE_ACCOUNT
    assert bot.has_usable_password() is False

    # Rejouée, la migration ne duplique pas.
    migration.backfill_service_accounts(django_apps, None)
    assert User.objects.filter(email=bot_email("legacy-tenant")).count() == 1


# ─── Invisibilité dans l'admin ───

def grant_admin_permissions(user):
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label__in=["iam", "voyage", "geo"])
    )
    return user


def admin_client(user):
    client = Client()
    client.force_login(grant_admin_permissions(user))
    return client


@pytest.fixture
def superadmin():
    return User.objects.create_user(
        email="super@toupac.sn", password="TestPass#2026", first_name="Super",
        last_name="Admin", tenant=None, role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True,
    )


def test_service_accounts_hidden_from_user_list_for_tenant_admin(user_admin_a, tenant_a):
    bot = User.objects.get(email=bot_email(tenant_a.slug))

    body = admin_client(user_admin_a).get("/admin/iam/user/").content.decode()

    assert str(user_admin_a.id) in body
    assert str(bot.id) not in body


def test_service_accounts_visible_to_superadmin(superadmin, tenant_a):
    bot = User.objects.get(email=bot_email(tenant_a.slug))

    body = admin_client(superadmin).get("/admin/iam/user/").content.decode()

    assert str(bot.id) in body


def test_service_accounts_hidden_from_user_dropdowns(user_admin_a, user_dispatcher_a, tenant_a):
    """Aucun flux ne demande de désigner un bot comme chauffeur ou créateur."""
    bot = User.objects.get(email=bot_email(tenant_a.slug))
    Route.objects.create(
        tenant=tenant_a, name="Route", code="AAA",
        origin_place=Place.objects.create(
            tenant=tenant_a, name="Origine", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        ),
        destination_place=Place.objects.create(
            tenant=tenant_a, name="Destination", type=Place.PlaceType.STATION,
            location=Point(-8.0029, 12.6392, srid=4326),
        ),
    )

    body = admin_client(user_admin_a).get("/admin/voyage/trip/add/").content.decode()

    assert str(user_dispatcher_a.id) in body  # les humains restent proposés
    assert str(bot.id) not in body
