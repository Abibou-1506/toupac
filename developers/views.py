"""TOUPAC Developers — Portails publics de documentation d'intégration.

Deux portails, deux publics. Un intégrateur qui branche l'ERP de sa compagnie et
une équipe partenaire qui sert toutes les compagnies n'ont ni les mêmes clés, ni
les mêmes en-têtes, ni les mêmes quotas. Les avoir réunis sur une page obligeait
chacun à ignorer la moitié du texte et à deviner laquelle. Chaque page renvoie à
l'autre en tête, pour qui serait arrivé au mauvais endroit.

Les deux vues sont publiques et sans authentification : c'est le point d'entrée
d'un partenaire qui n'a pas encore de clé.
"""
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.platform_services import PLATFORM_SERVICES
from iam.scopes import ADMIN_SCOPE, AVAILABLE_SCOPES

API_BASE_URL = "https://api.toupac.com"
SUPPORT_EMAIL = "contact@toupac.com"


class TenantDeveloperPortalView(TemplateView):
    """GET /developers/ — intégrations privées d'une compagnie (`ApiCredential`)."""

    template_name = "developers/tenant_portal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # La liste des scopes vient du code : la doc ne peut pas diverger.
        context["scopes"] = [
            {"name": name, "description": description, "is_admin": name == ADMIN_SCOPE}
            for name, description in AVAILABLE_SCOPES.items()
        ]
        context["api_base_url"] = API_BASE_URL
        context["support_email"] = SUPPORT_EMAIL
        context["rate_default"] = "1 000"
        context["rate_admin"] = "10 000"
        context["partner_portal_url"] = reverse_lazy("partner-developer-portal")
        return context


class PartnerDeveloperPortalView(TemplateView):
    """GET /partners/developers/ — services multi-compagnies (`PlatformCredential`)."""

    template_name = "developers/partner_portal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["platform_scopes"] = [
            {"name": name, "description": description}
            for name, description in PLATFORM_AVAILABLE_SCOPES.items()
        ]
        context["platform_services"] = [
            {"slug": slug, "label": spec["label"], "description": spec["description"]}
            for slug, spec in PLATFORM_SERVICES.items()
        ]
        context["api_base_url"] = API_BASE_URL
        context["support_email"] = SUPPORT_EMAIL
        context["rate_platform"] = "1 000"
        context["rate_acting_customer"] = "200"
        context["tenant_portal_url"] = reverse_lazy("developer-portal")
        return context
