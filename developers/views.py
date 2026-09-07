"""TOUPAC Developers — Portail développeur public (documentation d'intégration)."""
from django.views.generic import TemplateView

from iam.platform_scopes import PLATFORM_AVAILABLE_SCOPES
from iam.platform_services import PLATFORM_SERVICES
from iam.scopes import ADMIN_SCOPE, AVAILABLE_SCOPES


class DeveloperPortalView(TemplateView):
    """
    GET /developers/ — page de documentation destinée aux intégrateurs tiers.

    Publique et sans authentification : c'est le point d'entrée d'un
    partenaire qui n'a pas encore de clé.
    """

    template_name = "developers/portal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # La liste des scopes vient du code : la doc ne peut pas diverger.
        context["scopes"] = [
            {"name": name, "description": description, "is_admin": name == ADMIN_SCOPE}
            for name, description in AVAILABLE_SCOPES.items()
        ]
        # Même principe côté plateforme : la doc dérive du code, elle ne peut
        # pas annoncer un scope ou un service qui n'existe pas.
        context["platform_scopes"] = [
            {"name": name, "description": description}
            for name, description in PLATFORM_AVAILABLE_SCOPES.items()
        ]
        context["platform_services"] = [
            {"slug": slug, "label": spec["label"], "description": spec["description"]}
            for slug, spec in PLATFORM_SERVICES.items()
        ]
        context["api_base_url"] = "https://api.toupac.com"
        context["support_email"] = "contact@toupac.com"
        context["rate_default"] = "1 000"
        context["rate_admin"] = "10 000"
        return context
