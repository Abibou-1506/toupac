"""Routes IAM côté ressources (hors auth / plateforme / customer).

Monté sous /api/v1/iam/ dans config/urls.py. Volontairement distinct
d'`iam.urls` qui héberge /api/v1/auth/{login,me,refresh,logout,otp/*},
pour qu'un ajout de ressource utilisateur ne modifie pas le préfixe de
la famille auth.
"""
from django.urls import path

from .views import UserListByRoleView

urlpatterns = [
    path("users/", UserListByRoleView.as_view(), name="iam-user-list-by-role"),
]
