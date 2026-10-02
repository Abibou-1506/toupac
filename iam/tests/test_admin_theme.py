"""
TOUPAC IAM — Tests smoke pour la refonte du thème admin (Ticket 1 T2).

Vérifie que :
- /admin/ répond 200 pour superadmin ET admin de compagnie après refonte
  (préservation stricte 902 tests, zéro régression admin) ;
- la callback is_toupac_superadmin continue de masquer les items plateforme
  à un admin de compagnie dans la sidebar rendue ;
- environment_badge retourne la bonne forme selon TOUPAC_ENVIRONMENT.

Pattern : django.test.Client() + force_login, assertions HTML sur URL
(pas sur libellé — DECISIONS.md).
"""
import pytest
from django.test import Client, override_settings
from django.urls import reverse

from iam.unfold import environment_badge

# ─── Smoke /admin/ ───

@pytest.mark.django_db
def test_admin_root_responds_200_for_superadmin(superadmin):
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_root_responds_200_for_tenant_admin(user_admin_a):
    """La refonte UNFOLD ne doit pas casser l'accès admin aux admins de compagnie."""
    client = Client()
    client.force_login(user_admin_a)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200


# ─── Permission callback sidebar — préservation ───

@pytest.mark.django_db
def test_platform_sidebar_items_visible_to_superadmin(superadmin):
    """Un superadmin voit les items plateforme dans la sidebar."""
    client = Client()
    client.force_login(superadmin)
    response = client.get(reverse("admin:index"))
    content = response.content.decode()
    assert "/admin/iam/platformcredential/" in content
    assert "/admin/iam/platformauditlog/" in content


@pytest.mark.django_db
def test_platform_sidebar_items_hidden_from_tenant_admin(user_admin_a):
    """Un admin de compagnie ne doit PAS voir les items plateforme.

    Assertion sur l'URL (/admin/iam/platformcredential/), pas sur le
    libellé « Clés plateforme » — cf. DECISIONS.md, « Assertions HTML
    sur URL/attributs, pas sur labels affichés ».
    """
    client = Client()
    client.force_login(user_admin_a)
    response = client.get(reverse("admin:index"))
    content = response.content.decode()
    assert "/admin/iam/platformcredential/" not in content
    assert "/admin/iam/platformauditlog/" not in content


# ─── environment_badge ───

@override_settings(TOUPAC_ENVIRONMENT="development")
def test_environment_badge_development():
    assert environment_badge(request=None) == ["Développement", "warning"]


@override_settings(TOUPAC_ENVIRONMENT="staging")
def test_environment_badge_staging():
    assert environment_badge(request=None) == ["Recette", "info"]


@override_settings(TOUPAC_ENVIRONMENT=None)
def test_environment_badge_none_when_unset():
    """None = pas de badge, pas d'erreur. Vrai en prod."""
    assert environment_badge(request=None) is None


@override_settings(TOUPAC_ENVIRONMENT="production")
def test_environment_badge_none_in_production():
    """« production » explicite retourne aussi None — la prod ne porte aucun badge."""
    assert environment_badge(request=None) is None
