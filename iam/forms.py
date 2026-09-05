"""TOUPAC IAM — Formulaires d'administration."""
from django import forms

from core.admin import TenantAdminMixin
from iam.models import ApiCredential
from iam.scopes import ADMIN_SCOPE, get_scope_choices


class ApiCredentialCreateForm(forms.ModelForm):
    """
    Formulaire d'émission d'une clé API depuis l'admin.

    `scopes` est un JSONField sur le modèle : sans ce formulaire, l'opérateur
    devrait saisir la liste en JSON à la main, avec le risque de fautes de
    frappe silencieuses. Les choix viennent de `iam.scopes`, source unique
    partagée avec le portail développeur.

    Les champs générés (préfixe, hash) sont absents : ils sont produits par
    `ApiCredential.issue()`, pas saisis.
    """

    #: Posé par ApiCredentialAdmin.get_form. None hors admin : la validation
    #: d'`admin:*` refuse alors par défaut, plutôt que d'ouvrir faute de contexte.
    _request = None

    scopes = forms.MultipleChoiceField(
        choices=get_scope_choices,
        widget=forms.CheckboxSelectMultiple,
        label="Scopes",
        help_text=(
            "Accorder au plus juste. `admin:*` couvre tout et reste réservé aux "
            "intégrations internes TOUPAC."
        ),
    )

    class Meta:
        model = ApiCredential
        # Pas de `user` : le porteur est le compte de service du tenant, posé
        # par l'admin. Demander à l'opérateur de désigner un humain n'avait pas
        # de sens produit et rendait la clé tributaire de sa présence.
        fields = ["name", "tenant", "scopes", "expires_at"]

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        if request is not None:
            self._request = request

    def clean_scopes(self):
        """
        `admin:*` est refusé à tout émetteur qui n'est pas superadmin TOUPAC.

        Le scope reste visible dans la liste : le masquer laisserait
        l'utilisateur chercher pourquoi il ne peut pas « tout autoriser ».
        L'afficher et expliquer le refus vaut mieux qu'un choix escamoté.
        """
        scopes = self.cleaned_data.get("scopes", [])
        if ADMIN_SCOPE not in scopes:
            return scopes

        issuer = getattr(self._request, "user", None)
        if issuer is None or not TenantAdminMixin._is_superadmin(issuer):
            raise forms.ValidationError(
                f"Le scope {ADMIN_SCOPE} est réservé aux intégrations internes TOUPAC. "
                "Pour vos propres besoins d'intégration, sélectionnez uniquement "
                "les scopes correspondant aux opérations attendues."
            )
        return scopes
