"""Tests V1.1 — RouteStop.arrival_offset_minutes / departure_offset_minutes."""
import importlib

import pytest
from django.contrib.gis.geos import Point
from django.test import TestCase

from geo.models import Place
from iam.models import Tenant
from voyage.models import Route, RouteStop

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Offsets", slug="offsets-tenant")


@pytest.fixture
def route(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar O", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    dest = Place.objects.create(
        tenant=tenant, name="Bamako O", type=Place.PlaceType.STATION,
        location=Point(-8.0, 12.65, srid=4326),
    )
    return Route.objects.create(
        tenant=tenant, name="R Offsets", code="R-OFF-01",
        origin_place=origin, destination_place=dest,
    )


@pytest.fixture
def intermediate_place(tenant):
    return Place.objects.create(
        tenant=tenant, name="Tamba O", type=Place.PlaceType.STATION,
        location=Point(-13.6673, 13.7707, srid=4326),
    )


def test_default_offsets_are_zero(tenant, route, intermediate_place):
    """Création sans spécifier d'offsets → tout à 0."""
    stop = RouteStop.objects.create(
        tenant=tenant, route=route, place=intermediate_place, stop_order=1,
    )
    assert stop.arrival_offset_minutes == 0
    assert stop.departure_offset_minutes == 0
    assert stop.offset_minutes == 0


def test_departure_syncs_offset_minutes_on_save(tenant, route, intermediate_place):
    """`offset_minutes` (deprecated) est synchronisé sur departure au save."""
    stop = RouteStop.objects.create(
        tenant=tenant, route=route, place=intermediate_place, stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=630,
    )
    assert stop.offset_minutes == 630
    stop.departure_offset_minutes = 720
    stop.save()
    stop.refresh_from_db()
    assert stop.offset_minutes == 720


def test_arrival_can_differ_from_departure(tenant, route, intermediate_place):
    """Pause longue : arrival et departure distincts, les 2 champs persistés."""
    stop = RouteStop.objects.create(
        tenant=tenant, route=route, place=intermediate_place, stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=630,
    )
    stop.refresh_from_db()
    assert stop.arrival_offset_minutes == 600
    assert stop.departure_offset_minutes == 630
    assert stop.departure_offset_minutes - stop.arrival_offset_minutes == 30


def test_legacy_offset_minutes_backfills_arrival_departure(
    tenant, route, intermediate_place,
):
    """Code historique qui écrit seulement `offset_minutes` → le save() override
    reporte la valeur sur arrival/departure si eux sont à 0.
    """
    stop = RouteStop(
        tenant=tenant, route=route, place=intermediate_place, stop_order=1,
        offset_minutes=300,
    )
    stop.save()
    stop.refresh_from_db()
    assert stop.arrival_offset_minutes == 300
    assert stop.departure_offset_minutes == 300
    assert stop.offset_minutes == 300


class TestBackfillMigration(TestCase):
    """Vérifie que la migration data est atomique (1 requête SQL via F())."""

    def test_backfill_populates_new_fields_in_single_query(self):
        # Setup : 3 RouteStop legacy avec offset_minutes seulement
        tenant = Tenant.objects.create(name="Backfill T", slug="backfill-t")
        origin = Place.objects.create(
            tenant=tenant, name="OB", type=Place.PlaceType.STATION,
            location=Point(-17.0, 14.0, srid=4326),
        )
        dest = Place.objects.create(
            tenant=tenant, name="DB", type=Place.PlaceType.STATION,
            location=Point(-16.0, 14.5, srid=4326),
        )
        route = Route.objects.create(
            tenant=tenant, name="RB", code="RB-01",
            origin_place=origin, destination_place=dest,
        )
        # Reset explicite des 2 nouveaux champs à 0 pour simuler l'état
        # pré-migration (le save() les aurait synchronisés sinon).
        RouteStop.objects.create(
            tenant=tenant, route=route, place=origin, stop_order=0,
            offset_minutes=100,
        )
        RouteStop.objects.create(
            tenant=tenant, route=route, place=dest, stop_order=1,
            offset_minutes=250,
        )
        RouteStop.objects.filter(route=route).update(
            arrival_offset_minutes=0,
            departure_offset_minutes=0,
        )

        migration = importlib.import_module(
            "voyage.migrations.0007_backfill_routestop_offsets",
        )

        class DummyApps:
            @staticmethod
            def get_model(app, model):
                from django.apps import apps as django_apps
                return django_apps.get_model(app, model)

        with self.assertNumQueries(1):
            migration.backfill(DummyApps, None)

        for stop in RouteStop.objects.filter(route=route):
            assert stop.arrival_offset_minutes == stop.offset_minutes
            assert stop.departure_offset_minutes == stop.offset_minutes


def test_serializer_exposes_three_offsets(tenant, route, intermediate_place):
    """RouteStopSerializer renvoie les 3 champs (compat RN + V1.1)."""
    from voyage.serializers import RouteStopSerializer

    stop = RouteStop.objects.create(
        tenant=tenant, route=route, place=intermediate_place, stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=630,
    )
    data = RouteStopSerializer(stop).data
    assert data["arrival_offset_minutes"] == 600
    assert data["departure_offset_minutes"] == 630
    assert data["offset_minutes"] == 630  # deprecated, miroir de departure
