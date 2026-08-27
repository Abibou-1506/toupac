from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import DeliveryTaskViewSet, DispatchView, OrderViewSet, ParcelViewSet

router = DefaultRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("parcels", ParcelViewSet, basename="parcel")
router.register("delivery-tasks", DeliveryTaskViewSet, basename="delivery-task")

urlpatterns = [
    path("dispatch/optimize/", DispatchView.as_view(), name="dispatch-optimize"),
] + router.urls
