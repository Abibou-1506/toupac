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
        fields = ["name", "tenant", "user", "scopes", "expires_at"]

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        if request is not None:
            self._request = request
        # Le porteur reste obligatoire, bien que le modèle l'autorise à null :
        # ApiKeyAuthentication refuse une clé orpheline (il lui faut un
        # request.user pour IsAuthenticated). Une clé sans porteur serait
        # créée sans erreur puis rejetée en 401 à chaque appel.
        if "user" in self.fields:
            self.fields["user"].required = True
            self.fields["user"].help_text = (
                "Utilisateur au nom duquel la clé agit. Obligatoire : une clé sans "
                "porteur est refusée à l'authentification."
            )

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

    def clean(self):
        cleaned = super().clean()
        tenant, user = cleaned.get("tenant"), cleaned.get("user")
        # Un porteur d'un autre tenant ferait diverger request.user.tenant du
        # tenant que l'authentificateur attache depuis la clé.
        if tenant and user and user.tenant_id != tenant.id:
            self.add_error("user", "Ce porteur appartient à une autre compagnie.")
        return cleaned
