from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import GeofenceViewSet, PositionViewSet, PublicTrackingView, TrackingLinkViewSet

router = DefaultRouter()
router.register("positions", PositionViewSet, basename="position")
router.register("geofences", GeofenceViewSet, basename="geofence")
router.register("links", TrackingLinkViewSet, basename="tracking-link")

urlpatterns = [
    # Doit précéder le router : sinon le ViewSet "links" intercepte /links/<token>/
    # en tentant de l'interpréter comme un lookup par PK.
    path("links/<str:token>/", PublicTrackingView.as_view(), name="public-tracking"),
] + router.urls
