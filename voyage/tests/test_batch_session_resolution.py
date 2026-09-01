"""
TOUPAC Voyage — Résolution de la ControlSession dans le batch offline.

Le champ `session_id` du body couvre le cas où le contrôleur ferme la session A,
ouvre la B, puis resynchronise tardivement les events accumulés dans A : sans lui
le backend rattachait ces events à B, la seule session ouverte au moment du sync.
"""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from voyage.models import ControlEvent, Controller, ControlSession, Route, Trip

pytestmark = pytest.mark.django_db

BATCH_URL = "/api/v1/voyage/control-events/batch/"


@pytest.fixture(autouse=True)
def _isolated_throttle_cache(settings):
    """Isole le compteur de throttling du Redis de dev."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "toupac-tests",
        }
    }
    cache.clear()
    yield
    cache.clear()


# ─── Fabriques ───

def make_tenant(slug="acme"):
    return Tenant.objects.create(name=f"Transport {slug}", slug=slug)


def make_controller(tenant, email, matricule):
    user = User.objects.create_user(
        email=email, password="x", first_name="Moussa", last_name="Sarr",
        tenant=tenant, role=User.Role.CONTROLLER,
    )
    controller = Controller.objects.create(tenant=tenant, user=user, matricule=matricule)
    return user, controller


def make_trip(tenant, code="DKR-BKO"):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Bamako", type=Place.PlaceType.STATION,
        location=Point(-8.0029, 12.6392, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code=code,
        origin_place=origin, destination_place=destination,
    )
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id=f"VYG-{code}",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45,
    )


def make_session(tenant, controller, trip, closed=False):
    return ControlSession.objects.create(
        tenant=tenant, trip=trip, controller=controller, device_id="DEVICE-001",
        opened_at=timezone.now(),
        closed_at=timezone.now() if closed else None,
    )


def an_event():
    """Event minimal accepté par le processor — seul le rattachement est testé ici."""
    return {
        "client_uuid": str(uuid.uuid4()),
        "event_type": "activity_transition",
        "payload": {"to_status": Trip.Status.PREPARING},
        "created_at_local": timezone.now().isoformat(),
    }


def post_batch(user, body):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(BATCH_URL, body, format="json")


# ─── Tests ───

def test_batch_without_session_id_uses_active_session():
    tenant = make_tenant()
    user, controller = make_controller(tenant, "c1@acme.sn", "CH-001")
    trip = make_trip(tenant)
    make_session(tenant, controller, trip, closed=True)
    active = make_session(tenant, controller, trip)

    response = post_batch(user, {"events": [an_event()]})

    assert response.status_code == 200, response.data
    assert response.data["session_id"] == str(active.id)
    assert response.data["results"][0]["status"] == "accepted"
    assert ControlEvent.objects.get().session_id == active.id


def test_batch_with_valid_session_id_uses_it_even_if_closed():
    tenant = make_tenant()
    user, controller = make_controller(tenant, "c1@acme.sn", "CH-001")
    trip = make_trip(tenant)
    closed = make_session(tenant, controller, trip, closed=True)
    make_session(tenant, controller, trip)  # session ouverte, à ne PAS choisir

    response = post_batch(user, {"session_id": str(closed.id), "events": [an_event()]})

    assert response.status_code == 200, response.data
    assert response.data["session_id"] == str(closed.id)
    assert response.data["results"][0]["status"] == "accepted"
    assert ControlEvent.objects.get().session_id == closed.id


def test_batch_with_session_id_of_another_controller_returns_403():
    tenant = make_tenant()
    user, _ = make_controller(tenant, "c1@acme.sn", "CH-001")
    _, other_controller = make_controller(tenant, "c2@acme.sn", "CH-002")
    trip = make_trip(tenant)
    foreign = make_session(tenant, other_controller, trip)

    response = post_batch(user, {"session_id": str(foreign.id), "events": [an_event()]})

    assert response.status_code == 403
    assert response.data["detail"] == "Cette session n'appartient pas au contrôleur authentifié."
    assert not ControlEvent.objects.exists()


def test_batch_with_unknown_session_id_returns_404():
    tenant = make_tenant()
    user, controller = make_controller(tenant, "c1@acme.sn", "CH-001")
    trip = make_trip(tenant)
    make_session(tenant, controller, trip)

    response = post_batch(user, {"session_id": str(uuid.uuid4()), "events": [an_event()]})

    assert response.status_code == 404
    assert response.data["detail"] == "Session introuvable."
    assert not ControlEvent.objects.exists()


def test_batch_with_malformed_session_id_returns_400():
    tenant = make_tenant()
    user, controller = make_controller(tenant, "c1@acme.sn", "CH-001")
    trip = make_trip(tenant)
    make_session(tenant, controller, trip)

    response = post_batch(user, {"session_id": "pas-un-uuid", "events": [an_event()]})

    assert response.status_code == 400
    assert response.data["detail"] == "session_id invalide (UUID attendu)."
    assert not ControlEvent.objects.exists()


def test_batch_without_session_id_and_no_active_session_returns_400():
    tenant = make_tenant()
    user, controller = make_controller(tenant, "c1@acme.sn", "CH-001")
    trip = make_trip(tenant)
    make_session(tenant, controller, trip, closed=True)

    response = post_batch(user, {"events": [an_event()]})

    assert response.status_code == 400
    assert response.data["detail"] == "Aucune session de contrôle active."
    assert not ControlEvent.objects.exists()
