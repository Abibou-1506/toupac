from rest_framework.routers import DefaultRouter

from .views import DriverViewSet, FleetViewSet, VehicleTypeViewSet, VehicleViewSet

router = DefaultRouter()
router.register("vehicle-types", VehicleTypeViewSet, basename="vehicle-type")
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("drivers", DriverViewSet, basename="driver")
router.register("fleets", FleetViewSet, basename="fleet")

urlpatterns = router.urls
