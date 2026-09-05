"""TOUPAC Core — Mixins et helpers pour Django Admin."""
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q


class TenantAdminMixin:
    """
    Isole les données par tenant dans l'admin Django.

    À appliquer sur tout ModelAdmin dont le modèle porte un tenant. Le
    TenantManager ne filtre rien tout seul : côté API ce sont les ViewSets qui
    appellent `.filter(tenant=request.tenant)`, côté admin personne ne le
    faisait — d'où la fuite que ce mixin ferme.

    Cinq points d'application :
    - `get_queryset` : la liste ne montre que le tenant courant ;
    - `has_view/change/delete_permission(obj)` : accès direct par URL à un
      objet d'un autre tenant refusé ;
    - `formfield_for_foreignkey` : les dropdowns ne proposent pas de
      références d'un autre tenant ;
    - `save_model` : à la création, le tenant courant est imposé — un tenant
      forgé dans le formulaire est ignoré.

    Les superadmins (`is_superuser` ou `role=SUPERADMIN`) court-circuitent
    tout : l'accès transverse fait partie de leur travail.
    """

    #: Chemin vers le tenant. Accepte un lookup (« user__tenant ») pour les
    #: modèles rattachés indirectement — leur tenant est alors en lecture
    #: seule, `save_model` ne peut pas le poser.
    tenant_field = "tenant"

    #: True si les objets à tenant NULL sont partagés et doivent rester
    #: visibles (places publiques). Ils restent non modifiables hors superadmin.
    shared_visible = False

    @staticmethod
    def _is_superadmin(user):
        from iam.models import User

        return bool(user.is_superuser or getattr(user, "role", None) == User.Role.SUPERADMIN)

    def _obj_tenant(self, obj):
        """Résout le tenant de l'objet, en suivant `tenant_field` s'il est un lookup."""
        value = obj
        for part in self.tenant_field.split("__"):
            value = getattr(value, part, None)
            if value is None:
                return None
        return value

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self._is_superadmin(request.user):
            return queryset
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            # Staff sans tenant et non superadmin : situation anormale, on ne
            # montre rien plutôt que de tout montrer.
            return queryset.none()
        if self.shared_visible:
            return queryset.filter(
                Q(**{self.tenant_field: tenant}) | Q(**{f"{self.tenant_field}__isnull": True})
            )
        return queryset.filter(**{self.tenant_field: tenant})

    def _obj_belongs_to_user(self, request, obj):
        if obj is None or self._is_superadmin(request.user):
            return True
        tenant = getattr(request.user, "tenant", None)
        obj_tenant = self._obj_tenant(obj)
        return tenant is not None and obj_tenant is not None and obj_tenant == tenant

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if (
            self.shared_visible
            and obj is not None
            and self._obj_tenant(obj) is None
            and not self._is_superadmin(request.user)
        ):
            return True  # objet partagé : consultable, mais pas modifiable
        return self._obj_belongs_to_user(request, obj)

    def get_readonly_fields(self, request, obj=None):
        """
        Le tenant est en lecture seule hors superadmin.

        C'est ce qui rend `save_model` opérant : un champ readonly est retiré
        du formulaire, donc une valeur forgée dans le POST est ignorée au lieu
        d'être validée. Readonly plutôt qu'exclu, car plusieurs ModelAdmin
        (UserAdmin) listent `tenant` dans leurs fieldsets — un champ exclu y
        provoquerait une erreur de rendu, un champ readonly s'y affiche.
        """
        readonly = list(super().get_readonly_fields(request, obj))
        if (
            not self._is_superadmin(request.user)
            and "__" not in self.tenant_field
            and self.tenant_field not in readonly
            and self._model_has_tenant_field()
        ):
            readonly.append(self.tenant_field)
        return readonly

    def _model_has_tenant_field(self):
        try:
            self.model._meta.get_field(self.tenant_field)
        except FieldDoesNotExist:
            return False
        return True

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._obj_belongs_to_user(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._obj_belongs_to_user(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not self._is_superadmin(request.user):
            tenant = getattr(request.user, "tenant", None)
            related = db_field.related_model
            if tenant is not None and related is not None:
                kwargs.setdefault("queryset", self._scoped_related_queryset(related, tenant))
                if kwargs["queryset"] is None:
                    kwargs.pop("queryset")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @staticmethod
    def _scoped_related_queryset(related, tenant):
        """Queryset du modèle lié restreint au tenant, ou None s'il n'est pas concerné."""
        from iam.models import Tenant, User

        if related is Tenant:
            return Tenant.objects.filter(pk=tenant.pk)
        try:
            field = related._meta.get_field("tenant")
        except FieldDoesNotExist:
            return None
        queryset = related._default_manager.all()

        # tenant NULL n'a pas le même sens selon le modèle. Sur une Place ou un
        # NotificationTemplate il veut dire « partagé entre compagnies » ; sur
        # un User il veut dire « personnel interne TOUPAC ». Aucun flux métier
        # ne demande à un admin de compagnie de désigner un salarié TOUPAC, et
        # les lister exposerait leurs noms — on les exclut.
        if related is User:
            # Les comptes de service (porteurs techniques des clés API) sont
            # exclus au même titre : aucun flux ne demande de désigner un bot
            # comme chauffeur, contrôleur ou créateur.
            return queryset.filter(tenant=tenant).exclude(role=User.Role.SERVICE_ACCOUNT)

        if field.null:
            # Objet partagé : il doit rester sélectionnable, sinon on ne peut
            # plus créer une Route, dont les lieux d'origine et de destination
            # sont des gares publiques.
            return queryset.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
        return queryset.filter(tenant=tenant)

    def save_model(self, request, obj, form, change):
        # Uniquement à la création : sur un objet existant, get_queryset et
        # has_change_permission garantissent déjà le bon tenant, et le
        # réécrire reviendrait à déplacer l'objet.
        if not change and not self._is_superadmin(request.user) and "__" not in self.tenant_field:
            tenant = getattr(request.user, "tenant", None)
            if tenant is not None:
                # Imposé sans condition : si l'on ne remplaçait que la valeur
                # absente, un tenant forgé dans le formulaire passerait.
                setattr(obj, self.tenant_field, tenant)
        super().save_model(request, obj, form, change)


class SuperadminOnlyAdminMixin:
    """Réserve un ModelAdmin aux superadmins — pour les modèles sans tenant propre (Tenant)."""

    def has_module_permission(self, request):
        return super().has_module_permission(request) and TenantAdminMixin._is_superadmin(request.user)

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and TenantAdminMixin._is_superadmin(request.user)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and TenantAdminMixin._is_superadmin(request.user)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and TenantAdminMixin._is_superadmin(request.user)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and TenantAdminMixin._is_superadmin(request.user)
