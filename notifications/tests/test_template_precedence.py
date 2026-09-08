"""
TOUPAC Notifications — Le gabarit d'une compagnie l'emporte sur le générique.

C'est la promesse du docstring de `_find_template`, et la raison d'être du
`tenant` nullable sur `NotificationTemplate` : une compagnie doit pouvoir
réécrire un message sans que TOUPAC ne le fasse pour elle.

Aucun test ne la couvrait — tous passent par `make_template()`, qui crée un
gabarit système.
"""
import pytest

from notifications.catalog import get_event
from notifications.models import Notification, NotificationTemplate
from notifications.services import NotificationService
from notifications.tests.emit_helpers import (
    TICKET_EVENT,
    make_template,
    resolver_returning,
    temporary_resolver,
    ticket_context,
)

pytestmark = pytest.mark.django_db


def test_a_tenant_template_wins_over_the_system_one(tenant_a, client_fatou):
    make_template(TICKET_EVENT, "in_app", title_template="Système")
    make_template(TICKET_EVENT, "in_app", tenant=tenant_a, title_template="Compagnie")

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(),
            tenant=tenant_a, channels=["in_app"],
        )

    assert Notification.objects.get().title == "Compagnie"


def test_the_system_template_serves_when_the_company_has_none(tenant_a, client_fatou):
    """Le générique reste le filet : sans surcharge, il doit servir."""
    make_template(TICKET_EVENT, "in_app", title_template="Système")

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(),
            tenant=tenant_a, channels=["in_app"],
        )

    assert Notification.objects.get().title == "Système"


def test_the_template_of_another_company_is_never_served(
    tenant_a, tenant_b, client_fatou,
):
    """
    Une surcharge appartient à sa compagnie.

    Sans le filtre, le tri par `tenant_id` ferait remonter n'importe quelle
    surcharge — celle d'un concurrent comprise.
    """
    make_template(TICKET_EVENT, "in_app", title_template="Système")
    make_template(TICKET_EVENT, "in_app", tenant=tenant_b, title_template="Concurrent")

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(),
            tenant=tenant_a, channels=["in_app"],
        )

    assert Notification.objects.get().title == "Système"


def test_an_inactive_tenant_template_falls_back_to_the_system_one(tenant_a, client_fatou):
    """Désactiver une surcharge doit rendre la main au générique, pas éteindre."""
    make_template(TICKET_EVENT, "in_app", title_template="Système")
    make_template(
        TICKET_EVENT, "in_app", tenant=tenant_a,
        title_template="Compagnie", is_active=False,
    )

    with temporary_resolver(
        get_event(TICKET_EVENT).resolver_key, resolver_returning(client_fatou),
    ):
        NotificationService.emit(
            event_code=TICKET_EVENT, context=ticket_context(),
            tenant=tenant_a, channels=["in_app"],
        )

    assert Notification.objects.get().title == "Système"


def test_the_lookup_prefers_the_tenant_row_directly(tenant_a):
    """
    Le tri lui-même, sans passer par une émission.

    Utile au diagnostic : si le test d'émission tombe, celui-ci dit si la cause
    est le tri ou ce qui l'entoure.
    """
    system = make_template(TICKET_EVENT, "in_app", title_template="Système")
    company = make_template(
        TICKET_EVENT, "in_app", tenant=tenant_a, title_template="Compagnie",
    )

    found = NotificationService._find_template(
        tenant=tenant_a, event_code=TICKET_EVENT, channel="in_app", language="fr",
    )

    assert found.pk == company.pk
    assert found.pk != system.pk
    assert NotificationTemplate.objects.count() == 2
