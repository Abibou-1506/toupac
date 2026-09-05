"""TOUPAC IAM — Formulaires d'administration."""
from django import forms

from iam.models import ApiCredential
from iam.scopes import get_scope_choices


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

    scopes = forms.MultipleChoiceField(
        choices=get_scope_choices,
        widget=forms.CheckboxSelectMultiple,
        label="Scopes",
        help_text="Accorder au plus juste. `admin:*` couvre tout et reste réservé aux SI internes.",
    )

    class Meta:
        model = ApiCredential
        fields = ["name", "tenant", "user", "scopes", "expires_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def clean(self):
        cleaned = super().clean()
        tenant, user = cleaned.get("tenant"), cleaned.get("user")
        # Un porteur d'un autre tenant ferait diverger request.user.tenant du
        # tenant que l'authentificateur attache depuis la clé.
        if tenant and user and user.tenant_id != tenant.id:
            self.add_error("user", "Ce porteur appartient à une autre compagnie.")
        return cleaned
