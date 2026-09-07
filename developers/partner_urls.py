"""Routes du portail partenaires, montées sur /partners/.

Fichier distinct de `developers/urls.py` : les deux portails vivent sous des
préfixes différents (`/developers/` et `/partners/developers/`), et un seul
`urlpatterns` ne peut pas être monté deux fois avec des sous-chemins distincts.
"""
from django.urls import path

from .views import PartnerDeveloperPortalView

urlpatterns = [
    path("developers/", PartnerDeveloperPortalView.as_view(), name="partner-developer-portal"),
]
