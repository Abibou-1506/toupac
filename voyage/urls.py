from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    RouteViewSet, ScheduleViewSet, TripViewSet, ReservationViewSet,
    PassengerViewSet, ControllerViewSet, ControlEventBatchView,
)

router = DefaultRouter()
router.register("routes", RouteViewSet, basename="route")
router.register("schedules", ScheduleViewSet, basename="schedule")
router.register("trips", TripViewSet, basename="trip")
router.register("reservations", ReservationViewSet, basename="reservation")
router.register("passengers", PassengerViewSet, basename="passenger")
router.register("controllers", ControllerViewSet, basename="controller")

urlpatterns = [
    path("control-events/batch/", ControlEventBatchView.as_view(), name="control-events-batch"),
] + router.urls
