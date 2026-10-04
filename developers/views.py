"""TOUPAC Developers — Portail public de documentation d'intégration.

Un seul portail depuis le pivot du 4 oct 2026 (TOUPAC entité unique) : les
intégrations partenaires passent toutes par le mode plateforme
(`PlatformCredential`). L'ancien portail « tenant » destiné à l'ADMIN d'une
compagnie cliente externe a été supprimé — ce public n'existe plus.

La vue reste publique et sans authentification : c'est le point d'entrée d'un
partenaire qui n'a pas encore de clé.
"""
from django.views.generic import TemplateView

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.platform_services import PLATFORM_SERVICES

API_BASE_URL = "https://api.toupac.com"
SUPPORT_EMAIL = "contact@toupac.com"


class PartnerDeveloperPortalView(TemplateView):
    """GET /partners/developers/ — intégrations partenaires (`PlatformCredential`)."""

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
        return context
