from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import NotificationLogViewSet, NotificationTemplateViewSet, SendNotificationView

router = DefaultRouter()
router.register("templates", NotificationTemplateViewSet, basename="notification-template")
router.register("logs", NotificationLogViewSet, basename="notification-log")

urlpatterns = [
    path("send/", SendNotificationView.as_view(), name="notifications-send"),
] + router.urls
