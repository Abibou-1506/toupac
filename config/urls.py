from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.dashboard_views import DashboardActivitiesView, DashboardKPIsView


def health_check(request):
    return JsonResponse({"status": "ok", "service": "toupac"})

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    # toupac-web (cookies HTTP-only) : avant iam.urls pour que
    # /api/v1/auth/{login,refresh,logout}/ aillent aux vues cookie,
    # et que /api/v1/auth/{me,otp/*}/ tombent dans iam.urls ci-dessous.
    path("api/v1/", include("iam.urls_auth")),
    path("api/v1/auth/", include("iam.urls")),
    path("api/v1/platform/", include("iam.platform_urls")),
    path("api/v1/customer/", include("iam.customer_urls")),
    path("api/v1/voyage/", include("voyage.urls")),
    path("api/v1/colis/", include("colis.urls")),
    path("api/v1/billing/", include("billing.urls")),
    path("api/v1/tracking/", include("tracking.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/fleet/", include("fleet.urls")),
    path("api/v1/geo/", include("geo.urls")),
    path("api/v1/workflows/", include("workflow.urls")),
    # Dashboard : endpoints transverses hébergés dans core/. Pas d'app
    # dédiée tant que le périmètre reste 2 widgets ; extraction V1.2 si
    # croissance.
    path("api/v1/dashboard/kpis/", DashboardKPIsView.as_view(), name="dashboard-kpis"),
    path("api/v1/dashboard/activities/", DashboardActivitiesView.as_view(), name="dashboard-activities"),
    path("partners/", include("developers.partner_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
