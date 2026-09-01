from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def health_check(request):
    return JsonResponse({"status": "ok", "service": "toupac"})

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("api/v1/auth/", include("iam.urls")),
    path("api/v1/voyage/", include("voyage.urls")),
    path("api/v1/colis/", include("colis.urls")),
    path("api/v1/billing/", include("billing.urls")),
    path("api/v1/tracking/", include("tracking.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/fleet/", include("fleet.urls")),
    path("api/v1/geo/", include("geo.urls")),
    path("api/v1/workflows/", include("workflow.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
