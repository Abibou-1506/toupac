from django.urls import path

from .views import DeveloperPortalView

urlpatterns = [
    path("", DeveloperPortalView.as_view(), name="developer-portal"),
]
