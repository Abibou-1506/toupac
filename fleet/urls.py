from rest_framework.routers import DefaultRouter

from .views import (
    DriverDocumentViewSet,
    DriverHRNoteViewSet,
    DriverViewSet,
    FleetViewSet,
    VehicleMaintenanceViewSet,
    VehicleTypeViewSet,
    VehicleViewSet,
)

router = DefaultRouter()
router.register("vehicle-types", VehicleTypeViewSet, basename="vehicle-type")
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("drivers", DriverViewSet, basename="driver")
router.register("fleets", FleetViewSet, basename="fleet")
router.register(
    "vehicle-maintenances",
    VehicleMaintenanceViewSet,
    basename="vehicle-maintenance",
)
router.register(
    "driver-hr-notes", DriverHRNoteViewSet, basename="driver-hr-note",
)
router.register(
    "driver-documents", DriverDocumentViewSet, basename="driver-document",
)

urlpatterns = router.urls
