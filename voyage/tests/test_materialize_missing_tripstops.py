"""Tests de la commande `materialize_missing_tripstops`.

Rattrapage des Trips historiques crees avant le signal post_save du 7 oct 2026.
Idempotente, filtrable par tenant, dry-run possible. Partage sa logique avec
le signal via `voyage.services.trip_stops.materialize_trip_stops`.
"""
from datetime import UTC, datetime
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command

from geo.models import Place
from iam.models import Tenant
from voyage.models import Route, RouteStop, Trip

pytestmark = pytest.mark.django_db


def _make_tenant(slug: str) -> Tenant:
    return Tenant.objects.create(name=f"Tenant {slug}", slug=slug)


def _make_route_with_stops(tenant: Tenant, code: str) -> Route:
    origin = Place.objects.create(
        tenant=tenant, name=f"Origine {code}", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    dest = Place.objects.create(
        tenant=tenant, name=f"Dest {code}", type=Place.PlaceType.STATION,
        location=Point(-8.0, 12.65, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name=f"R {code}", code=code,
        origin_place=origin, destination_place=dest,
    )
    RouteStop.objects.create(
        tenant=tenant, route=route, place=origin, stop_order=0,
        arrival_offset_minutes=0, departure_offset_minutes=0,
    )
    RouteStop.objects.create(
        tenant=tenant, route=route, place=dest, stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=600,
    )
    return route


def _make_trip(tenant: Tenant, route: Route, internal_id: str) -> Trip:
    scheduled = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
    return Trip.objects.create(
        tenant=tenant, route=route,
        internal_id=internal_id,
        departure_date=scheduled.date(),
        scheduled_at=scheduled,
        total_seats=45,
    )


def test_command_on_empty_db_reports_zero():
    out = StringIO()
    call_command("materialize_missing_tripstops", stdout=out)
    output = out.getvalue().lower()
    assert "0 trip" in output


def test_command_is_idempotent():
    tenant = _make_tenant("idem")
    route = _make_route_with_stops(tenant, "R-IDEM-01")
    trip = _make_trip(tenant, route, "T-IDEM-20261007-00")
    # Le signal a deja materialise les stops a la creation.
    before = trip.stops.count()
    assert before == 2

    out = StringIO()
    call_command("materialize_missing_tripstops", stdout=out)
    assert trip.stops.count() == before


def test_dry_run_does_not_write():
    tenant = _make_tenant("dry")
    route = _make_route_with_stops(tenant, "R-DRY-01")
    trip = _make_trip(tenant, route, "T-DRY-20261007-00")
    # Simule un Trip orphelin : le signal a tourne, on vide manuellement.
    trip.stops.all().delete()
    assert trip.stops.count() == 0

    out = StringIO()
    call_command("materialize_missing_tripstops", "--dry-run", stdout=out)
    output = out.getvalue()
    assert "1 Trip" in output
    assert "[dry-run]" in output
    assert trip.stops.count() == 0


def test_tenant_filter_scopes_to_single_tenant():
    tenant_a = _make_tenant("tenant-a")
    tenant_b = _make_tenant("tenant-b")
    route_a = _make_route_with_stops(tenant_a, "R-A-01")
    route_b = _make_route_with_stops(tenant_b, "R-B-01")
    trip_a = _make_trip(tenant_a, route_a, "T-A-20261007-00")
    trip_b = _make_trip(tenant_b, route_b, "T-B-20261007-00")
    trip_a.stops.all().delete()
    trip_b.stops.all().delete()

    out = StringIO()
    call_command("materialize_missing_tripstops", "--tenant", "tenant-a", stdout=out)

    assert trip_a.stops.count() > 0
    assert trip_b.stops.count() == 0


def test_verbose_lists_each_trip():
    tenant = _make_tenant("verb")
    route = _make_route_with_stops(tenant, "R-VERB-01")
    trip = _make_trip(tenant, route, "T-VERB-20261007-00")
    trip.stops.all().delete()

    out = StringIO()
    call_command("materialize_missing_tripstops", "--verbose", stdout=out)
    output = out.getvalue()
    assert "T-VERB-20261007-00" in output
