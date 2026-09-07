"""TOUPAC IAM — Routes des endpoints plateforme (montées sur /api/v1/platform/)."""
from django.urls import path

from .platform_views import PlatformHealthView, PlatformNotificationsView, PlatformTenantsView

urlpatterns = [
    path("tenants/", PlatformTenantsView.as_view(), name="platform-tenants"),
    path("health/", PlatformHealthView.as_view(), name="platform-health"),
    path("notifications/", PlatformNotificationsView.as_view(), name="platform-notifications"),
]
