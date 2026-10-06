"""Tests Prompt 8 Bug B — matérialisation `TripStop` à la création d'un `Trip`.

Signal `materialize_tripstops_on_trip_creation` branché sur `post_save(Trip)`
avec `dispatch_uid`. Vérifie :
- 1 TripStop par RouteStop ordonné
- `eta = trip.scheduled_at + arrival_offset_minutes`
- Idempotence (save() d'un Trip déjà matérialisé ne duplique pas)
- Création via ORM direct (admin / seed) ou DRF serializer
- Isolation tenant
"""
from datetime import datetime, timedelta, timezone as dt_tz

import pytest
from django.contrib.gis.geos import Point

from geo.models import Place
from iam.models import Tenant
from voyage.models import Route, RouteStop, Trip, TripStop
from voyage.serializers import TripCreateSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Materialize T", slug="materialize-t")


@pytest.fixture
def route_with_stops(tenant):
    origin = Place.objects.create(
        tenant=tenant, name="Origine M", type=Place.PlaceType.STATION,
        location=Point(-17.44, 14.69, srid=4326),
    )
    middle_1 = Place.objects.create(
        tenant=tenant, name="Tamba M", type=Place.PlaceType.STATION,
        location=Point(-13.6673, 13.7707, srid=4326),
    )
    middle_2 = Place.objects.create(
        tenant=tenant, name="Kayes M", type=Place.PlaceType.STATION,
        location=Point(-11.4454, 14.4428, srid=4326),
    )
    dest = Place.objects.create(
        tenant=tenant, name="Dest M", type=Place.PlaceType.STATION,
        location=Point(-8.0, 12.65, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="R Materialize", code="R-MAT-01",
        origin_place=origin, destination_place=dest,
    )
    # 4 escales dans l'ordre. Pause 30 min à Tambacounda (arrival != departure).
    RouteStop.objects.create(
        tenant=tenant, route=route, place=origin, stop_order=0,
        arrival_offset_minutes=0, departure_offset_minutes=0,
    )
    RouteStop.objects.create(
        tenant=tenant, route=route, place=middle_1, stop_order=1,
        arrival_offset_minutes=600, departure_offset_minutes=630,
    )
    RouteStop.objects.create(
        tenant=tenant, route=route, place=middle_2, stop_order=2,
        arrival_offset_minutes=1080, departure_offset_minutes=1110,
    )
    RouteStop.objects.create(
        tenant=tenant, route=route, place=dest, stop_order=3,
        arrival_offset_minutes=1440, departure_offset_minutes=1440,
    )
    return route


def _make_trip(tenant, route, scheduled_at=None):
    return Trip.objects.create(
        tenant=tenant, route=route,
        internal_id="T-MAT-20261007-00",
        departure_date=(scheduled_at or datetime(2026, 10, 7, 8, 0, tzinfo=dt_tz.utc)).date(),
        scheduled_at=scheduled_at or datetime(2026, 10, 7, 8, 0, tzinfo=dt_tz.utc),
        total_seats=45,
    )


def test_trip_creation_materializes_tripstops_from_route(tenant, route_with_stops):
    trip = _make_trip(tenant, route_with_stops)
    assert trip.stops.count() == 4
    orders = list(trip.stops.order_by("stop_order").values_list("stop_order", flat=True))
    assert orders == [0, 1, 2, 3]
    # Chaque TripStop pointe vers le RouteStop d'origine.
    for ts in trip.stops.all():
        assert ts.route_stop.stop_order == ts.stop_order
        assert ts.route_stop.route_id == route_with_stops.id


def test_trip_creation_sets_eta_from_arrival_offset(tenant, route_with_stops):
    scheduled = datetime(2026, 10, 7, 8, 0, tzinfo=dt_tz.utc)
    trip = _make_trip(tenant, route_with_stops, scheduled_at=scheduled)
    stop_tamba = trip.stops.get(stop_order=1)
    stop_kayes = trip.stops.get(stop_order=2)
    # Tambacounda arrival = +10h (600 min)
    assert stop_tamba.eta == scheduled + timedelta(minutes=600)
    # Kayes arrival = +18h (1080 min)
    assert stop_kayes.eta == scheduled + timedelta(minutes=1080)
    # Tous les stops sont PENDING à la création.
    assert all(s.status == TripStop.Status.PENDING for s in trip.stops.all())


def test_signal_idempotent_on_resave(tenant, route_with_stops):
    trip = _make_trip(tenant, route_with_stops)
    assert trip.stops.count() == 4
    # Save sans created=True : le signal se déclenche mais la garde idempotente
    # (`stops.exists()` + `created=False`) empêche toute re-matérialisation.
    trip.status = Trip.Status.PREPARING
    trip.save()
    assert trip.stops.count() == 4


def test_trip_creation_via_drf_serializer_also_materializes(tenant, route_with_stops):
    """Admin et scripts créent via ORM ; DRF créé via serializer. Les deux chemins
    passent par `Trip.save()` → signal → stops matérialisés."""
    serializer = TripCreateSerializer(
        data={
            "route": str(route_with_stops.id),
            "departure_date": "2026-10-07",
            "scheduled_at": "2026-10-07T08:00:00Z",
            "total_seats": 45,
        },
    )
    # Pas de context[request] : on passe tenant au save().
    serializer.is_valid(raise_exception=True)
    trip = serializer.save(tenant=tenant)
    assert trip.stops.count() == 4
    assert set(trip.stops.values_list("stop_order", flat=True)) == {0, 1, 2, 3}


def test_tripstop_preserves_tenant_isolation(route_with_stops):
    """Un trip du tenant A matérialise des TripStop du tenant A (fuite impossible)."""
    tenant_a = route_with_stops.tenant
    trip = _make_trip(tenant_a, route_with_stops)
    assert trip.stops.count() == 4
    assert all(ts.tenant_id == tenant_a.id for ts in trip.stops.all())
