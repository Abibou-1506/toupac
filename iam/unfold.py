"""
TOUPAC IAM — Callbacks de visibilité pour la navigation Unfold.

La sidebar Unfold est déclarée en dur dans les settings : elle n'applique aucune
permission toute seule, contrairement à l'index admin natif qui masque les
modèles interdits. Sans ces callbacks, un admin de compagnie verrait les entrées
plateforme et récolterait un 403 en cliquant.

Hors des settings pour rester testables et pour que `UNFOLD` reste lisible.
Référencés par chemin pointé (`"iam.unfold.is_toupac_superadmin"`), ce qui évite
d'importer du code applicatif au chargement des settings.
"""
from django.conf import settings

from core.admin import TenantAdminMixin


def is_toupac_superadmin(request):
    """Vrai pour le personnel TOUPAC interne, faux pour un admin de compagnie."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    return TenantAdminMixin._is_superadmin(user)


def environment_badge(request):
    """
    Badge affiché en tête d'admin selon l'environnement de déploiement.

    Pilotée par `settings.TOUPAC_ENVIRONMENT`, posée à « development » en
    dev.py et à la valeur de l'env-var `TOUPAC_ENVIRONMENT` en prod.py.
    Retourne None quand il n'y a rien à afficher (vraie prod) : Unfold
    traite None comme « pas de badge », pas comme une erreur.

    Format de retour attendu par Unfold : [texte, color] où color est
    l'une des familles de palette de la UI (primary, secondary, success,
    info, warning, danger).
    """
    env = getattr(settings, "TOUPAC_ENVIRONMENT", None)
    if env == "development":
        return ["Développement", "warning"]
    if env == "staging":
        return ["Recette", "info"]
    return None


def dashboard_callback(request, context):
    """
    Peuple l'index admin avec les 4 stat cards TOUPAC.

    Admin de compagnie → stats de son tenant.
    Superadmin → stats globales (toutes compagnies agrégées).
    Staff sans tenant et non superadmin → stats vides. Situation anormale
    (TenantAdminMixin.get_queryset applique le même repli : « on ne
    montre rien plutôt que de tout montrer »).

    Format de retour : context modifié en place avec une clé `cards`,
    liste de dicts consommée par templates/admin/index.html.
    """
    from iam.dashboard import compute_stats

    user = request.user
    if TenantAdminMixin._is_superadmin(user):
        stats = compute_stats(tenant=None)
    elif getattr(user, "tenant", None) is not None:
        stats = compute_stats(tenant=user.tenant)
    else:
        # Staff orphelin : fail-safe cohérent avec TenantAdminMixin.
        stats = {
            "trips_today": 0,
            "orders_in_progress": 0,
            "incidents_open": 0,
            "revenue_month_xof": 0,
        }

    # Format XOF avec séparateurs milliers français (espace insécable U+00A0).
    # Pas d'intword pour XOF, format manuel : la locale fr_FR n'est pas
    # installée dans l'image Docker, un simple remplacement suffit. Le
    # NBSP est écrit sous forme d'échappement \\u00a0 plutôt que littéral
    # pour que la source reste lisible (ruff RUF001 bannit les caractères
    # ambigus en source — ici, le NBSP est voulu, pas un typo).
    nbsp = " "  # noqa: RUF001
    revenue_formatted = (
        f"{stats['revenue_month_xof']:,}".replace(",", nbsp) + " XOF"
    )

    context["cards"] = [
        {
            "title": "Voyages aujourd'hui",
            "value": stats["trips_today"],
            "icon": "directions_bus",
            "color": "primary",
        },
        {
            "title": "Commandes en cours",
            "value": stats["orders_in_progress"],
            "icon": "inventory_2",
            "color": "warning",
        },
        {
            "title": "Incidents ouverts",
            "value": stats["incidents_open"],
            "icon": "report_problem",
            "color": "danger",
        },
        {
            "title": "CA du mois",
            "value": revenue_formatted,
            "icon": "payments",
            "color": "success",
        },
    ]
    return context
