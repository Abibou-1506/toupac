"""Tests des restrictions par rôle sur l'admin Django (Ticket 4 Gamma).

Verrouille les 5 garde-fous mis en place :
- RoleRestrictedAdminMixin sur les 3 ModelAdmin financiers
- filter_actions_by_role sur les 2 bulk actions
- DRIVER is_staff=False imposé
- Items sidebar financiers masqués selon rôle (via permission callback)

La bannière (chantier C4) est purement cosmétique — vérification visuelle,
pas d'assertion automatisée (trop fragile à l'évolution Tailwind).
"""
import pytest
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory
from django.urls import reverse

from iam.models import User
from iam.unfold import is_admin_or_superadmin


@pytest.fixture
def rf():
    return RequestFactory()


def grant_full_permissions(user):
    """Accorde toutes les permissions de modèle à un user.

    Les ADMIN compagnie ne naissent pas avec les Permission Django — en
    production, c'est seed_demo qui les assigne via un groupe. Dans les
    tests, on les pose à la main pour que les asserts mesurent le mixin
    (restriction de rôle), pas l'absence de permission. Cohérent avec
    `grant_admin_permissions` dans test_admin_cross_tenant_isolation.
    """
    user.user_permissions.set(Permission.objects.all())
    return user


# ─── RoleRestrictedAdminMixin sur les 3 ModelAdmin financiers ───

@pytest.mark.django_db
@pytest.mark.parametrize("admin_url", [
    "admin:billing_invoice_changelist",
    "admin:billing_payment_changelist",
    "admin:billing_pricelist_changelist",
])
def test_financial_admins_accessible_to_admin_role(user_admin_a, admin_url):
    """Un ADMIN compagnie voit les écrans financiers (son tenant)."""
    grant_full_permissions(user_admin_a)
    client = Client()
    client.force_login(user_admin_a)
    response = client.get(reverse(admin_url))
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("admin_url", [
    "admin:billing_invoice_changelist",
    "admin:billing_payment_changelist",
    "admin:billing_pricelist_changelist",
])
def test_financial_admins_blocked_for_dispatcher(user_dispatcher_staff_a, admin_url):
    """Un DISPATCHER (is_staff=True + permissions) ne voit pas les écrans financiers (403)."""
    grant_full_permissions(user_dispatcher_staff_a)
    client = Client()
    client.force_login(user_dispatcher_staff_a)
    response = client.get(reverse(admin_url))
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("admin_url", [
    "admin:billing_invoice_changelist",
    "admin:billing_payment_changelist",
    "admin:billing_pricelist_changelist",
])
def test_financial_admins_blocked_for_agent(user_agent_staff_a, admin_url):
    """Un AGENT (is_staff=True + permissions) ne voit pas non plus les écrans financiers."""
    grant_full_permissions(user_agent_staff_a)
    client = Client()
    client.force_login(user_agent_staff_a)
    response = client.get(reverse(admin_url))
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("admin_url", [
    "admin:billing_invoice_changelist",
    "admin:billing_payment_changelist",
    "admin:billing_pricelist_changelist",
])
def test_financial_admins_accessible_to_superadmin(superadmin, admin_url):
    """SUPERADMIN TOUPAC voit toujours les écrans financiers."""
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse(admin_url))
    assert response.status_code == 200


# ─── Bulk actions restreintes ───

@pytest.mark.django_db
def test_cancel_reservations_action_hidden_from_agent(user_agent_staff_a):
    """La bulk action `cancel_reservations` n'apparaît pas pour un AGENT."""
    grant_full_permissions(user_agent_staff_a)
    client = Client()
    client.force_login(user_agent_staff_a)
    response = client.get(reverse("admin:voyage_reservation_changelist"))
    assert response.status_code == 200
    # L'action est présente dans le markup si visible dans le dropdown.
    assert "cancel_reservations" not in response.content.decode()


@pytest.mark.django_db
def test_cancel_reservations_action_visible_to_dispatcher(user_dispatcher_staff_a):
    """La bulk action `cancel_reservations` est visible pour un DISPATCHER."""
    grant_full_permissions(user_dispatcher_staff_a)
    client = Client()
    client.force_login(user_dispatcher_staff_a)
    response = client.get(reverse("admin:voyage_reservation_changelist"))
    assert response.status_code == 200
    assert "cancel_reservations" in response.content.decode()


@pytest.mark.django_db
def test_mark_as_resolved_hidden_from_agent(user_agent_staff_a):
    """`mark_as_resolved` sur Incident n'apparaît pas pour un AGENT."""
    grant_full_permissions(user_agent_staff_a)
    client = Client()
    client.force_login(user_agent_staff_a)
    response = client.get(reverse("admin:voyage_incident_changelist"))
    assert response.status_code == 200
    assert "mark_as_resolved" not in response.content.decode()


@pytest.mark.django_db
def test_mark_as_resolved_visible_to_controller(user_controller_staff_a):
    """`mark_as_resolved` sur Incident est accessible à CONTROLLER."""
    grant_full_permissions(user_controller_staff_a)
    client = Client()
    client.force_login(user_controller_staff_a)
    response = client.get(reverse("admin:voyage_incident_changelist"))
    assert response.status_code == 200
    assert "mark_as_resolved" in response.content.decode()


# ─── DRIVER is_staff=False imposé par User.clean() ───

@pytest.mark.django_db
def test_driver_cannot_be_is_staff_true(tenant_a):
    """Un DRIVER avec is_staff=True refuse le full_clean."""
    user = User(
        email="bad.driver@toupac.sn", first_name="Bad", last_name="Driver",
        tenant=tenant_a, role=User.Role.DRIVER, is_staff=True,
    )
    user.set_password("TestPass#2026")
    with pytest.raises(ValidationError) as exc_info:
        user.full_clean()
    assert "is_staff" in exc_info.value.message_dict


@pytest.mark.django_db
def test_driver_with_is_staff_false_is_valid(tenant_a):
    """Un DRIVER avec is_staff=False passe le full_clean."""
    user = User(
        email="good.driver@toupac.sn", first_name="Good", last_name="Driver",
        tenant=tenant_a, role=User.Role.DRIVER, is_staff=False,
    )
    user.set_password("TestPass#2026")
    user.full_clean()  # ne lève pas


# ─── Callback sidebar is_admin_or_superadmin ───

@pytest.mark.django_db
def test_is_admin_or_superadmin_accepts_superadmin(superadmin, rf):
    request = rf.get("/admin/")
    request.user = superadmin
    assert is_admin_or_superadmin(request) is True


@pytest.mark.django_db
def test_is_admin_or_superadmin_accepts_admin(user_admin_a, rf):
    request = rf.get("/admin/")
    request.user = user_admin_a
    assert is_admin_or_superadmin(request) is True


@pytest.mark.django_db
def test_is_admin_or_superadmin_rejects_dispatcher(user_dispatcher_staff_a, rf):
    request = rf.get("/admin/")
    request.user = user_dispatcher_staff_a
    assert is_admin_or_superadmin(request) is False


def test_is_admin_or_superadmin_rejects_anonymous(rf):
    """Un request anonyme → False (sécurité par défaut)."""
    request = rf.get("/admin/")
    request.user = AnonymousUser()
    assert is_admin_or_superadmin(request) is False
