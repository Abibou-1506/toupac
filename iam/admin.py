"""TOUPAC IAM — Configuration Django Admin + unfold."""
import time

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from unfold.admin import ModelAdmin

from core.admin import SuperadminOnlyAdminMixin, TenantAdminMixin

from .forms import ApiCredentialCreateForm, PlatformCredentialCreateForm
from .models import (
    ApiCredential,
    AuditLog,
    PlatformAuditLog,
    PlatformCredential,
    Tenant,
    User,
    UserDevice,
)


@admin.register(Tenant)
class TenantAdmin(SuperadminOnlyAdminMixin, ModelAdmin):
    """Tenant est la racine : il n'a pas de tenant. Réservé aux superadmins."""
    list_display = ["name", "country_code", "currency", "status", "subscription_plan", "created_at"]
    list_filter = ["status", "country_code", "subscription_plan"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]


@admin.register(User)
class UserAdmin(TenantAdminMixin, BaseUserAdmin, ModelAdmin):
    list_display = ["email", "first_name", "last_name", "role", "tenant", "is_active"]
    list_filter = ["role", "is_active", "tenant"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["last_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informations", {"fields": ("first_name", "last_name", "phone", "tenant", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login_at", "created_at", "updated_at", "deleted_at")}),
    )
    readonly_fields = ["created_at", "updated_at", "last_login_at"]
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "tenant", "role", "password1", "password2"),
        }),
    )

    #: Rôles qu'un admin de compagnie peut créer. CLIENT en est exclu (il
    #: n'appartient à aucune compagnie), SUPERADMIN aussi (escalade), et
    #: SERVICE_ACCOUNT également (les bots sont provisionnés par le code).
    TENANT_ADMIN_ASSIGNABLE_ROLES = (
        User.Role.ADMIN, User.Role.DISPATCHER, User.Role.AGENT,
        User.Role.DRIVER, User.Role.CONTROLLER,
    )

    def get_queryset(self, request):
        """
        Masque les comptes de service aux admins de compagnie.

        Un porteur technique de clés API n'est pas un utilisateur à
        administrer : le lister n'apporterait qu'une ligne incompréhensible
        dans la liste du personnel. Le superadmin le voit, pour diagnostic.
        """
        queryset = super().get_queryset(request)
        if self._is_superadmin(request.user):
            return queryset
        return queryset.exclude(role=User.Role.SERVICE_ACCOUNT)

    def get_form(self, request, obj=None, **kwargs):
        """
        Fait voir à la validation le tenant que `save_model` posera.

        `TenantAdminMixin` rend `tenant` lisible seul hors superadmin : le champ
        sort du formulaire, et le rattachement n'est appliqué qu'au moment du
        `save_model` — donc après la validation. `User.clean()` voyait alors un
        agent sans compagnie et refusait la création, en accrochant l'erreur à
        un champ que le formulaire ne contient pas (ValueError « has no field
        named tenant »). On pose donc la valeur sur l'instance avant validation.
        """
        form_class = super().get_form(request, obj, **kwargs)
        if self._is_superadmin(request.user):
            return form_class

        issuer_tenant = getattr(request.user, "tenant", None)

        def clean(self):
            cleaned = super(type(self), self).clean()
            # `construct_instance` ne réécrit que les champs présents dans le
            # formulaire : la valeur posée ici survit jusqu'à `full_clean()`.
            if "tenant" not in self.fields and self.instance.tenant_id is None:
                self.instance.tenant = issuer_tenant
            return cleaned

        return type(form_class.__name__, (form_class,), {"clean": clean})

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """
        Restreint les rôles proposés à un admin de compagnie.

        Le menu déroulant est la première barrière, mais pas la seule : un POST
        forgé contourne le HTML. `save_model` revalide, et la contrainte
        `user_tenant_matches_role` ferme le dernier recours.
        """
        if db_field.name == "role" and not self._is_superadmin(request.user):
            kwargs["choices"] = [
                (value, label) for value, label in User.Role.choices
                if value in self.TENANT_ADMIN_ASSIGNABLE_ROLES
            ]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """
        Dernier verrou sur le rôle attribué depuis l'admin d'une compagnie.

        Le menu déroulant restreint ne protège que l'interface : un POST forgé
        propose n'importe quelle valeur. La cohérence rôle/tenant, elle, est
        déjà vérifiée en amont — `ModelForm._post_clean()` appelle
        `User.clean()`, qui refuse un CLIENT avec compagnie ou un chauffeur
        sans. Il ne reste donc ici que la question « cet émetteur a-t-il le
        droit d'attribuer ce rôle ».
        """
        if (
            not self._is_superadmin(request.user)
            and obj.role not in self.TENANT_ADMIN_ASSIGNABLE_ROLES
        ):
            raise PermissionDenied(
                "Ce rôle ne peut pas être attribué depuis l'administration d'une compagnie."
            )
        super().save_model(request, obj, form, change)


@admin.register(ApiCredential)
class ApiCredentialAdmin(TenantAdminMixin, ModelAdmin):
    """
    Émission de clés API avec révélation unique du secret.

    Le secret n'existe en clair qu'entre `issue()` et l'affichage de la page
    de révélation. Il transite par la session (jamais par l'URL ni par le
    framework de messages, qui n'expire pas), est purgé à la première lecture
    et périmé au bout de cinq minutes.
    """

    list_display = ["name", "tenant", "key_prefix", "is_active", "last_used_at"]
    list_filter = ["is_active", "tenant"]

    #: Champs produits par issue(), jamais saisis.
    GENERATED_FIELDS = ["key_prefix", "key_hash", "last_used_at", "created_at", "updated_at"]

    SESSION_KEY = "_toupac_api_credential_reveal"
    REVEAL_TTL_SECONDS = 300

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            return super().get_form(request, obj, **kwargs)

        kwargs["form"] = ApiCredentialCreateForm
        form_class = super().get_form(request, obj, **kwargs)
        # Sous-classe dynamique plutôt que functools.partial : Django lit
        # `form_class.base_fields` dans get_fields(), attribut qu'un partial
        # n'expose pas. Le formulaire y lit qui émet la clé, pour refuser
        # `admin:*` à un non-superadmin.
        return type(form_class.__name__, (form_class,), {"_request": request})

    def get_readonly_fields(self, request, obj=None):
        # Seulement en édition : sur le formulaire de création, ces champs
        # n'existent pas encore et s'afficheraient vides.
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly += [field for field in self.GENERATED_FIELDS if field not in readonly]
        return readonly

    def save_form(self, request, form, change):
        if change:
            return super().save_form(request, form, change)

        # Appelé pour son effet de bord : ModelForm.save(commit=False) définit
        # form.save_m2m(), que Django invoque ensuite dans save_related. Sans
        # ça, l'ajout planterait sur un AttributeError. L'instance produite est
        # écartée : c'est issue() qui crée et persiste la vraie.
        super().save_form(request, form, change)

        # Le tenant n'est dans cleaned_data que pour un superadmin : pour les
        # autres, TenantAdminMixin l'a passé en readonly, donc hors formulaire.
        tenant = form.cleaned_data.get("tenant") or getattr(request.user, "tenant", None)
        credential, plaintext = ApiCredential.issue(
            tenant=tenant,
            name=form.cleaned_data["name"],
            scopes=form.cleaned_data["scopes"],
            # Porteur systématique : le compte de service du tenant. Appel
            # get_or_create, donc auto-guérison si quelqu'un l'a supprimé.
            user=tenant.get_or_create_service_account(),
            expires_at=form.cleaned_data.get("expires_at"),
        )

        AuditLog.objects.create(
            tenant=credential.tenant,
            user=request.user,
            action="api_credential.issued",
            resource_type="ApiCredential",
            resource_id=credential.id,
            # Le secret n'y figure pas : le préfixe suffit à tracer la clé.
            changes={
                "name": credential.name,
                "scopes": credential.scopes,
                "key_prefix": credential.key_prefix,
                "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
            },
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )

        credential._plaintext_reveal = plaintext
        return credential

    def save_model(self, request, obj, form, change):
        if not change and getattr(obj, "_plaintext_reveal", None):
            return  # déjà persisté par issue()
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        plaintext = getattr(obj, "_plaintext_reveal", None)
        if not plaintext:
            return super().response_add(request, obj, post_url_continue)

        request.session[self.SESSION_KEY] = {
            "credential_id": str(obj.pk),
            "secret": plaintext,
            "expires_epoch": time.time() + self.REVEAL_TTL_SECONDS,
        }
        return HttpResponseRedirect(
            reverse("admin:iam_apicredential_reveal", args=[obj.pk])
        )

    def get_urls(self):
        custom = [
            path(
                "reveal/<uuid:credential_id>/",
                self.admin_site.admin_view(self.reveal_view),
                name="iam_apicredential_reveal",
            ),
        ]
        return custom + super().get_urls()

    def reveal_view(self, request, credential_id):
        """Affiche le secret une seule fois, puis le retire de la session."""
        credential = get_object_or_404(self.get_queryset(request), pk=credential_id)
        change_url = reverse("admin:iam_apicredential_change", args=[credential.pk])

        # pop et non get : même en cas de rejet plus bas, le secret ne doit pas
        # survivre à cette requête.
        payload = request.session.pop(self.SESSION_KEY, None)
        if payload is None:
            self.message_user(
                request,
                "Ce secret a déjà été affiché. Il n'est plus récupérable — "
                "émettez une nouvelle clé si vous l'avez perdu.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        if payload.get("credential_id") != str(credential.pk):
            self.message_user(
                request, "Secret indisponible pour cette clé.", level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        if payload.get("expires_epoch", 0) < time.time():
            self.message_user(
                request,
                "Délai d'affichage dépassé : le secret a expiré. Émettez une nouvelle clé.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        context = {
            **self.admin_site.each_context(request),
            "title": "Clé API créée",
            "opts": self.model._meta,
            "credential": credential,
            "secret": payload["secret"],
            "change_url": change_url,
            "changelist_url": reverse("admin:iam_apicredential_changelist"),
        }
        return TemplateResponse(request, "admin/iam/apicredential/reveal.html", context)


@admin.register(AuditLog)
class AuditLogAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["action", "resource_type", "user", "tenant", "created_at"]
    list_filter = ["action", "resource_type"]
    readonly_fields = ["id", "tenant", "user", "action", "resource_type", "resource_id", "changes", "ip_address", "created_at"]
    search_fields = ["resource_type", "action"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(UserDevice)
class UserDeviceAdmin(TenantAdminMixin, ModelAdmin):
    # Pas de champ tenant propre : rattaché via son utilisateur.
    tenant_field = "user__tenant"

    list_display = ["user", "platform", "device_model", "is_active"]
    list_filter = ["platform", "is_active"]


# ─── Plateforme (services centraux TOUPAC) ───

@admin.register(PlatformCredential)
class PlatformCredentialAdmin(SuperadminOnlyAdminMixin, ModelAdmin):
    """
    Émission des clés de service plateforme, avec révélation unique du secret.

    Réservée au superadmin : une clé plateforme ouvre les données de tous les
    tenants abonnés, aucun admin de compagnie n'a à pouvoir en émettre. Même
    mécanique de révélation que les clés tenant — secret en session, purgé à la
    première lecture, périmé au bout de cinq minutes.
    """

    list_display = ["name", "platform_service", "key_prefix", "is_active", "expires_at", "last_used_at"]
    list_filter = ["platform_service", "is_active"]
    search_fields = ["name", "key_prefix", "platform_service"]

    #: Champs produits par issue(), jamais saisis.
    GENERATED_FIELDS = [
        "key_prefix", "key_hash", "last_used_at", "created_at", "updated_at", "created_by",
    ]

    SESSION_KEY = "_toupac_platform_credential_reveal"
    REVEAL_TTL_SECONDS = 300

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            return super().get_form(request, obj, **kwargs)
        kwargs["form"] = PlatformCredentialCreateForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        # Seulement en édition : sur le formulaire de création ces champs
        # n'existent pas encore et s'afficheraient vides.
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly += [field for field in self.GENERATED_FIELDS if field not in readonly]
        return readonly

    def save_form(self, request, form, change):
        if change:
            return super().save_form(request, form, change)

        # Appelé pour son effet de bord : ModelForm.save(commit=False) définit
        # form.save_m2m(), que Django invoque ensuite dans save_related. Sans ça
        # l'ajout planterait sur un AttributeError. L'instance produite est
        # écartée — c'est issue() qui crée et persiste la vraie.
        super().save_form(request, form, change)

        credential, plaintext = PlatformCredential.issue(
            name=form.cleaned_data["name"],
            platform_service=form.cleaned_data["platform_service"],
            platform_scopes=form.cleaned_data["platform_scopes"],
            allowed_ips=form.cleaned_data["allowed_ips"],
            expires_at=form.cleaned_data["expires_at"],
            created_by=request.user,
        )

        AuditLog.objects.create(
            # Pas de tenant : une clé plateforme n'appartient à aucun d'eux.
            tenant=None,
            user=request.user,
            action="platform_credential.issued",
            resource_type="PlatformCredential",
            resource_id=credential.id,
            # Le secret n'y figure pas : le préfixe suffit à tracer la clé.
            changes={
                "name": credential.name,
                "platform_service": credential.platform_service,
                "platform_scopes": credential.platform_scopes,
                "allowed_ips": credential.allowed_ips,
                "key_prefix": credential.key_prefix,
                # Nul pour une clé sans échéance, désormais le cas nominal.
                "expires_at": (
                    credential.expires_at.isoformat() if credential.expires_at else None
                ),
            },
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )

        credential._plaintext_reveal = plaintext
        return credential

    def save_model(self, request, obj, form, change):
        if not change and getattr(obj, "_plaintext_reveal", None):
            return  # déjà persisté par issue()
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        plaintext = getattr(obj, "_plaintext_reveal", None)
        if not plaintext:
            return super().response_add(request, obj, post_url_continue)

        request.session[self.SESSION_KEY] = {
            "credential_id": str(obj.pk),
            "secret": plaintext,
            "expires_epoch": time.time() + self.REVEAL_TTL_SECONDS,
        }
        return HttpResponseRedirect(
            reverse("admin:iam_platformcredential_reveal", args=[obj.pk])
        )

    def get_urls(self):
        custom = [
            path(
                "reveal/<uuid:credential_id>/",
                self.admin_site.admin_view(self.reveal_view),
                name="iam_platformcredential_reveal",
            ),
        ]
        return custom + super().get_urls()

    def reveal_view(self, request, credential_id):
        """Affiche le secret une seule fois, puis le retire de la session."""
        credential = get_object_or_404(self.get_queryset(request), pk=credential_id)
        change_url = reverse("admin:iam_platformcredential_change", args=[credential.pk])

        # pop et non get : même en cas de rejet plus bas, le secret ne doit pas
        # survivre à cette requête.
        payload = request.session.pop(self.SESSION_KEY, None)
        if payload is None:
            self.message_user(
                request,
                "Ce secret a déjà été affiché. Il n'est plus récupérable — "
                "émettez une nouvelle clé si vous l'avez perdu.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        if payload.get("credential_id") != str(credential.pk):
            self.message_user(
                request, "Secret indisponible pour cette clé.", level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        if payload.get("expires_epoch", 0) < time.time():
            self.message_user(
                request,
                "Délai d'affichage dépassé : le secret a expiré. Émettez une nouvelle clé.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(change_url)

        context = {
            **self.admin_site.each_context(request),
            "title": "Clé plateforme créée",
            "opts": self.model._meta,
            "credential": credential,
            "secret": payload["secret"],
            "change_url": change_url,
            "changelist_url": reverse("admin:iam_platformcredential_changelist"),
        }
        return TemplateResponse(request, "admin/iam/platformcredential/reveal.html", context)



@admin.register(PlatformAuditLog)
class PlatformAuditLogAdmin(SuperadminOnlyAdminMixin, ModelAdmin):
    """Journal des appels plateforme. Lecture stricte : c'est une pièce d'audit."""

    list_display = [
        "created_at", "credential", "method", "endpoint", "tenant_context",
        "acting_user", "status_code", "latency_ms",
    ]
    list_filter = ["status_code", "method", "credential", "tenant_context", "acting_user"]
    search_fields = ["endpoint", "ip", "acting_user__email", "acting_user__phone"]
    readonly_fields = [f.name for f in PlatformAuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
