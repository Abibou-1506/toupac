"""TOUPAC IAM — Formulaires d'administration."""
from datetime import timedelta
from ipaddress import ip_network

from django import forms
from django.utils import timezone

from core.admin import TenantAdminMixin
from iam.models import ApiCredential, PlatformCredential
from iam.platform_scopes import get_platform_scope_choices
from iam.platform_services import PLATFORM_SERVICES, get_platform_service_choices
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


class PlatformCredentialCreateForm(forms.ModelForm):
    """
    Formulaire d'émission d'une clé plateforme depuis l'admin.

    Réservé au superadmin TOUPAC (l'admin l'impose via SuperadminOnlyAdminMixin).
    Les champs générés — préfixe, hash — sont absents : ils sont produits par
    `PlatformCredential.issue()`, pas saisis.

    Deux garde-fous vivent ici plutôt que sur le modèle, parce qu'ils encadrent
    le geste d'émission et non l'état de la ligne : le service doit être déclaré
    en code, et une expiration renseignée doit laisser une vraie durée de vie.
    L'allowlist IP, elle, peut rester vide — tous les partenaires n'ont pas
    d'adresse de sortie stable.
    """

    platform_service = forms.ChoiceField(
        choices=get_platform_service_choices,
        label="Service plateforme",
        help_text="Déclaré dans iam/platform_services.py. Ajouter un service est une "
                  "décision de conception, pas une saisie d'exploitation.",
    )

    platform_scopes = forms.MultipleChoiceField(
        choices=get_platform_scope_choices,
        widget=forms.CheckboxSelectMultiple,
        label="Scopes plateforme",
        help_text="Accorder au plus juste. Il n'existe volontairement pas de super-scope "
                  "`platform:*` : chaque clé porte une liste explicite.",
    )

    allowed_ips = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "52.34.10.5/32\n10.0.0.0/24"}),
        required=False,
        label="IP autorisées (CIDR)",
        help_text="Un CIDR par ligne. Une IP seule est acceptée et traitée comme /32. "
                  "Laisser vide n'applique aucun filtrage d'origine — à réserver aux "
                  "services sans IP de sortie stable.",
    )

    class Meta:
        model = PlatformCredential
        fields = ["name", "platform_service", "platform_scopes", "allowed_ips", "expires_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sans échéance par défaut : imposer une rotation obligerait à
        # retransmettre le secret au partenaire à chaque échéance, ce qui
        # multiplie les occasions de le voir fuiter. La révocation immédiate et
        # la trace d'audit protègent mieux qu'une date.
        self.fields["expires_at"].required = False
        self.fields["expires_at"].help_text = (
            "Facultatif. Sans date, la clé reste valable jusqu'à sa révocation."
        )

    def clean_platform_service(self):
        service = self.cleaned_data["platform_service"]
        if service not in PLATFORM_SERVICES:
            raise forms.ValidationError(
                f"Service plateforme inconnu : {service!r}. Les services sont déclarés "
                "dans iam/platform_services.py."
            )
        return service

    def clean_allowed_ips(self):
        """Textarea → liste de CIDR, chaque ligne validée par la stdlib."""
        raw = self.cleaned_data.get("allowed_ips", "") or ""
        cidrs = [line.strip() for line in raw.splitlines() if line.strip()]

        invalid = []
        for cidr in cidrs:
            try:
                ip_network(cidr, strict=False)
            except ValueError:
                invalid.append(cidr)
        if invalid:
            raise forms.ValidationError(
                f"CIDR invalide(s) : {', '.join(invalid)}. Exemple attendu : 52.34.10.5/32."
            )

        return cidrs

    def clean_expires_at(self):
        expires_at = self.cleaned_data.get("expires_at")
        if expires_at is None:
            return None
        if expires_at < timezone.now() + timedelta(hours=12):
            raise forms.ValidationError(
                "Une clé datée doit rester valide au moins 12 heures après son émission. "
                "Laissez le champ vide pour une clé sans échéance."
            )
        return expires_at
