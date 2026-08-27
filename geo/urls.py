from rest_framework.routers import DefaultRouter
from .views import PlaceViewSet, ZoneViewSet

router = DefaultRouter()
router.register("places", PlaceViewSet, basename="place")
router.register("zones", ZoneViewSet, basename="zone")

urlpatterns = router.urls
