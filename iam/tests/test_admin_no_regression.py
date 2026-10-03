"""Garde-fou : chaque ModelAdmin TOUPAC répond 200 pour un superadmin
après tous les enrichissements du Ticket 3.

Verrouille contre les erreurs silencieuses de type `select_related` sur
un champ absent, autocomplete sur un admin sans search_fields,
filter sur un champ qui n'existe plus, fieldset qui référence un champ
retiré du modèle, etc. Un test paramétré par ModelAdmin enregistré.

Pattern : django.test.Client + force_login, pas APIClient.
"""
import pytest
from django.contrib.admin import site
from django.test import Client
from django.urls import reverse

# Fige la liste au moment de la collection pytest : importer `site` ici
# déclenche les admin.py de toutes les apps installées (fait au startup
# Django), donc le registry est stable au moment où les tests sont
# paramétrés.
ALL_MODEL_ADMINS = sorted(
    (model._meta.app_label, model._meta.model_name)
    for model in site._registry
)


@pytest.mark.django_db
@pytest.mark.parametrize("app_label,model_name", ALL_MODEL_ADMINS)
def test_each_admin_changelist_responds_200_for_superadmin(
    superadmin, app_label, model_name,
):
    """Chaque changelist répond 200. ~43 tests paramétrés.

    Les erreurs silencieuses du Ticket 3 (select_related sur un champ
    renommé, autocomplete sur un modèle sans search_fields, filter sur
    un champ absent) remontent ici comme un 500 ou un ImproperlyConfigured.
    """
    client = Client()
    client.force_login(superadmin)
    url = reverse(f"admin:{app_label}_{model_name}_changelist")
    response = client.get(url)
    assert response.status_code == 200, (
        f"{app_label}.{model_name} changelist crashe pour superadmin "
        f"(status={response.status_code})"
    )
