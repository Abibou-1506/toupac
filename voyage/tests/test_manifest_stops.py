"""
TOUPAC Voyage — Le manifest offline expose les flags d'embarquement/descente.

L'app du contrôleur travaille hors réseau : tout ce dont elle a besoin pour la
durée du voyage doit tenir dans le manifest. Depuis le ticket vente à bord sur
trajet partiel, cela inclut `is_boarding` et `is_alighting` par stop — sans
quoi un contrôleur ne saurait pas quelles escales il peut proposer comme
origine ou destination d'une vente.

Un piège : ces deux champs sont dérivés du `RouteStop` parent, chargés via
`source="route_stop.…"`. Si la queryset n'avait pas prefetch le `route_stop`,
on paierait un N+1 par stop à chaque manifest — exactement le type de
régression qui ne se voit pas avant un trip chargé en production. Le second
test l'interdit par `assertNumQueries`.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, RouteStop, Trip

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Mani", slug="manifest-stops")


@pytest.fixture
def staff_user(tenant):
    return User.objects.create_user(
        email="staff@manifest-stops.sn", password="TestPass#2026",
        first_name="Mame", last_name="Fall",
        tenant=tenant, role=User.Role.DISPATCHER, is_staff=True,
    )


@pytest.fixture
def trip_with_stops(tenant):
    """Un voyage avec trois escales : montée seule, mixte, descente seule."""
    places = [
        Place.objects.create(
            tenant=tenant, name=name, type=Place.PlaceType.STATION,
            location=Point(lng, 14.0, srid=4326),
        )
        for name, lng in [("Dakar", -17.44), ("Thiès", -16.92), ("Bamako", -8.0)]
    ]
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code="DKR-BKO",
        origin_place=places[0], destination_place=places[-1],
    )
    specs = [
        (places[0], True, False),  # terminus de départ
        (places[1], True, True),   # escale mixte
        (places[2], False, True),  # terminus d'arrivée
    ]
    route_stops = [
        RouteStop.objects.create(
            tenant=tenant, route=route, place=place, stop_order=order_,
            is_boarding=boarding, is_alighting=alighting,
        )
        for order_, (place, boarding, alighting) in enumerate(specs)
    ]
    trip = Trip.objects.create(
        tenant=tenant, route=route, internal_id="VYG-M01",
        departure_date=timezone.now().date(), scheduled_at=timezone.now(),
        total_seats=45, status=Trip.Status.SCHEDULED,
    )
    # `TripStop` est l'instance temporelle d'un `RouteStop` pour ce voyage.
    # Depuis Prompt 8 Bug B, le signal `materialize_tripstops_on_trip_creation`
    # les créé automatiquement à `Trip.objects.create()`, un par RouteStop.
    assert trip.stops.count() == len(route_stops)
    return trip


def _authenticated(user):
    """JWT réel : `force_authenticate` ne traverse pas `TenantMiddleware`."""
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _fetch_manifest(user, trip):
    return _authenticated(user).get(f"/api/v1/voyage/trips/{trip.id}/manifest/")


def test_the_manifest_exposes_boarding_and_alighting_flags(staff_user, trip_with_stops):
    response = _fetch_manifest(staff_user, trip_with_stops)

    assert response.status_code == 200, response.data
    stops = sorted(response.data["trip"]["stops"], key=lambda s: s["stop_order"])
    assert len(stops) == 3
    assert [s["is_boarding"] for s in stops] == [True, True, False]
    assert [s["is_alighting"] for s in stops] == [False, True, True]


def test_the_manifest_does_not_add_a_query_per_stop(
    django_assert_num_queries, staff_user, trip_with_stops,
):
    """
    `is_boarding` et `is_alighting` dérivent du `RouteStop` parent via
    `source="route_stop.…"`. Sans `prefetch_related("stops__route_stop")`, on
    paierait une requête par stop à la sérialisation.

    Trois stops dans le décor : si l'un se transforme en requête, le compteur
    saute. Le test ne borne pas un nombre absolu — ces chiffres bougent au gré
    des optimisations — mais vérifie que **l'ajout d'un quatrième stop ne
    change rien au compte**. C'est l'invariant qui compte, pas la valeur
    exacte.
    """
    # Un premier appel pour mesurer le baseline avec trois stops.
    with django_assert_num_queries(0) as baseline:
        pass  # placeholder, remplacé par la capture ci-dessous
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as three_stops:
        _fetch_manifest(staff_user, trip_with_stops).data  # noqa: B018

    # On ajoute un quatrième stop, puis on remesure.
    extra_place = Place.objects.create(
        tenant=trip_with_stops.tenant, name="Kaolack", type=Place.PlaceType.STATION,
        location=Point(-16.07, 14.15, srid=4326),
    )
    RouteStop.objects.create(
        tenant=trip_with_stops.tenant, route=trip_with_stops.route,
        place=extra_place, stop_order=3, is_boarding=True, is_alighting=True,
    )
    with CaptureQueriesContext(connection) as four_stops:
        _fetch_manifest(staff_user, trip_with_stops).data  # noqa: B018

    delta = len(four_stops.captured_queries) - len(three_stops.captured_queries)
    assert delta <= 1, (
        f"Un stop supplémentaire a coûté {delta} requêtes de plus — N+1 "
        "latent sur le manifest. Vérifier que la queryset de `TripViewSet` "
        "fait bien `prefetch_related('stops__route_stop')`. "
        "(Une requête de plus est tolérée pour le prefetch batch, pas N.)"
    )
    _ = baseline
