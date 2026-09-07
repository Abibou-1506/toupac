from django.urls import path

from .views import TenantDeveloperPortalView

urlpatterns = [
    path("", TenantDeveloperPortalView.as_view(), name="developer-portal"),
]
