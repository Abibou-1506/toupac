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
from core.admin import TenantAdminMixin


def is_toupac_superadmin(request):
    """Vrai pour le personnel TOUPAC interne, faux pour un admin de compagnie."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    return TenantAdminMixin._is_superadmin(user)
