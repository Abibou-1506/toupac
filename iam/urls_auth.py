"""Routes d'auth pour le front toupac-web (JWT en cookies HTTP-only).

Monté sous /api/v1/ AVANT iam.urls dans config/urls.py pour qu'une
requête login/refresh/logout aille à la version cookie, tandis que
les autres routes (me/, otp/*) tombent dans iam.urls comme avant.
"""
from django.urls import path

from .views_auth_cookie import (
    CookieLogoutView,
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
)

urlpatterns = [
    path("auth/login/", CookieTokenObtainPairView.as_view(), name="auth-cookie-login"),
    path("auth/refresh/", CookieTokenRefreshView.as_view(), name="auth-cookie-refresh"),
    path("auth/logout/", CookieLogoutView.as_view(), name="auth-cookie-logout"),
]
