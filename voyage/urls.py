from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ControlEventBatchView,
    ControlEventLookupView,
    ControllerViewSet,
    IncidentViewSet,
    PassengerViewSet,
    QrPublicKeyView,
    ReservationViewSet,
    RouteViewSet,
    ScheduleViewSet,
    SeatMapViewSet,
    TripViewSet,
)

router = DefaultRouter()
router.register("routes", RouteViewSet, basename="route")
router.register("schedules", ScheduleViewSet, basename="schedule")
router.register("trips", TripViewSet, basename="trip")
router.register("reservations", ReservationViewSet, basename="reservation")
router.register("passengers", PassengerViewSet, basename="passenger")
router.register("controllers", ControllerViewSet, basename="controller")
router.register("incidents", IncidentViewSet, basename="incident")
router.register("seat-maps", SeatMapViewSet, basename="seat-map")

urlpatterns = [
    path("control-events/batch/", ControlEventBatchView.as_view(), name="control-events-batch"),
    # Le path converter `<uuid:...>` filtre au niveau URL : un path non-UUID
    # retombe en 404 Django natif avant même d'atteindre la vue. La route
    # DOIT être montée avant `*router.urls` pour éviter tout masquage par
    # un futur routeur sur le préfixe `control-events`.
    path(
        "control-events/<uuid:client_uuid>/",
        ControlEventLookupView.as_view(),
        name="control-events-lookup",
    ),
    path("qr-public-key/", QrPublicKeyView.as_view(), name="qr-public-key"),
    *router.urls,
]
