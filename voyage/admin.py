"""TOUPAC Voyage — Configuration Django Admin + unfold.

Enrichi au Ticket 3 :
- Badges statut colorés sur les 5 admins avec statut métier (Trip,
  Reservation, Anomaly, ControlEvent, Incident) via render_status_badge.
- list_select_related sur chaque admin dont list_display contient une FK.
- readonly_fields pour les champs auto-remplis (created_at, updated_at,
  resolved_at…) selon le modèle.
- date_hierarchy sur les admins avec un champ date naturel pour trier.
- Fieldsets français groupés sur 4 admins « lourds » : Trip, Reservation,
  Passenger, Incident.
- autocomplete_fields sur les FK à grande cardinalité (Trip, Reservation).
- Filtres Unfold overlay (DropdownFilter, RangeDateFilter) sur les 5 admins
  statut.
- Bulk actions : « Marquer résolu » (Incident), « Annuler » (Reservation).
"""
from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action

from core.admin import TenantAdminMixin, render_status_badge

from .models import (
    Anomaly,
    CashEntry,
    ControlEvent,
    Controller,
    ControlSession,
    Incident,
    LuggagePolicy,
    Passenger,
    PassengerAccessLog,
    Reservation,
    Route,
    RouteStop,
    Schedule,
    SeatMap,
    Trip,
    TripStop,
)


class RouteStopInline(TabularInline):
    model = RouteStop
    extra = 0


class TripStopInline(TabularInline):
    model = TripStop
    extra = 0


@admin.register(LuggagePolicy)
class LuggagePolicyAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "included_kg", "max_kg", "excess_price_per_kg_xof", "max_pieces", "tenant"]
    list_select_related = ["tenant"]
    list_filter = [("tenant", RelatedDropdownFilter)]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Route)
class RouteAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "code", "origin_place", "destination_place", "distance_km", "is_active", "tenant"]
    list_select_related = ["origin_place", "destination_place", "tenant"]
    list_filter = ["is_active", ("tenant", RelatedDropdownFilter)]
    search_fields = ["name", "code"]
    inlines = [RouteStopInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Schedule)
class ScheduleAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["route", "departure_time", "default_vehicle_type", "default_price_xof", "is_active", "tenant"]
    list_select_related = ["route", "default_vehicle_type", "tenant"]
    list_filter = ["is_active", ("route", RelatedDropdownFilter), ("tenant", RelatedDropdownFilter)]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SeatMap)
class SeatMapAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "vehicle_type", "total_seats", "tenant"]
    list_select_related = ["vehicle_type", "tenant"]
    list_filter = [("vehicle_type", RelatedDropdownFilter), ("tenant", RelatedDropdownFilter)]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Trip)
class TripAdmin(TenantAdminMixin, ModelAdmin):
    # status_badge remplace status dans list_display (C1). Les autres
    # changements : list_select_related sur toutes les FK, filtres overlay,
    # autocomplete, date_hierarchy, fieldsets français groupés.
    list_display = [
        "internal_id", "route", "departure_date", "status_badge",
        "booked_seats", "total_seats", "vehicle", "driver",
    ]
    list_select_related = ["route", "vehicle", "driver", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("departure_date", RangeDateFilter),
        ("route", RelatedDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["internal_id"]
    autocomplete_fields = ["route", "vehicle", "driver"]
    date_hierarchy = "departure_date"
    inlines = [TripStopInline]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("internal_id", "route", "schedule", "status")}),
        ("Dates", {"fields": ("departure_date", "scheduled_at", "actual_departure_at", "actual_arrival_at")}),
        ("Capacité", {"fields": ("total_seats", "booked_seats", "seat_map")}),
        ("Flotte", {"fields": ("vehicle", "driver")}),
        ("Résumé", {"fields": ("summary",), "classes": ("collapse",)}),
        ("Métadonnées", {"fields": ("tenant", "created_by", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(Passenger)
class PassengerAdmin(TenantAdminMixin, ModelAdmin):
    list_display = [
        "first_name", "last_name", "phone", "email", "nationality", "customer_user", "tenant",
    ]
    list_select_related = ["customer_user", "tenant"]
    # `customer_user__isnull` sépare les passagers rattachés à un compte TOUPAC
    # des invités — c'est la question qu'on se pose devant cette liste.
    list_filter = [
        "nationality",
        ("customer_user", admin.EmptyFieldListFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = [
        "first_name", "last_name", "phone", "email", "id_number",
        "customer_user__email", "customer_user__phone",
    ]
    autocomplete_fields = ["customer_user"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Informations", {"fields": ("first_name", "last_name", "phone", "email")}),
        ("Identité", {"fields": ("nationality", "id_type", "id_number", "id_photo_url", "date_of_birth")}),
        ("Contact d'urgence", {"fields": ("emergency_contact_name", "emergency_contact_phone")}),
        ("Compte TOUPAC", {"fields": ("customer_user",)}),
        ("Métadonnées", {"fields": ("tenant", "metadata", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Reservation)
class ReservationAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["trip", "passenger", "seat_label", "status_badge", "amount_xof", "payment_method"]
    list_select_related = ["trip", "passenger", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        "payment_method",
        "sales_channel",
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["seat_label", "passenger__first_name", "passenger__last_name"]
    autocomplete_fields = ["trip", "passenger"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at"]
    actions = ["cancel_reservations"]
    fieldsets = (
        ("Informations", {"fields": ("trip", "passenger", "seat_label", "status")}),
        ("Trajet", {"fields": ("origin_stop", "destination_stop", "boarded_at")}),
        ("Prix", {"fields": ("amount_xof", "payment_method", "sales_channel")}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())

    @action(description="Annuler les réservations", icon="cancel")
    def cancel_reservations(self, request, queryset):
        """Passe les réservations sélectionnées au statut CANCELLED.

        N'écrase pas les statuts terminaux (déjà annulées, no-show, embarquées,
        refusées) — idempotent et respectueux du cycle de vie.

        **Hors scope** : pas de refund paiement ici. Une annulation
        administrative est une correction technique ; le refund opérationnel
        passe par un workflow séparé.
        """
        count = queryset.exclude(
            status__in=[
                Reservation.Status.CANCELLED,
                Reservation.Status.NO_SHOW,
                Reservation.Status.BOARDED,
                Reservation.Status.REFUSED,
            ],
        ).update(status=Reservation.Status.CANCELLED)
        self.message_user(request, f"{count} réservation(s) annulée(s).")


@admin.register(Controller)
class ControllerAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["user", "matricule", "agency", "score_conformity", "total_trips", "status", "tenant"]
    list_select_related = ["user", "tenant"]
    list_filter = [("status", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    search_fields = ["matricule", "user__first_name", "user__last_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ControlSession)
class ControlSessionAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["trip", "controller", "opened_at", "closed_at", "sync_state", "tenant"]
    list_select_related = ["trip", "controller", "tenant"]
    list_filter = [("sync_state", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ControlEvent)
class ControlEventAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["session", "event_type", "status_badge", "created_at_local", "processed_at", "tenant"]
    list_select_related = ["session", "tenant"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("event_type", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    date_hierarchy = "created_at_local"
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(Anomaly)
class AnomalyAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["title", "type", "severity", "status_badge", "session", "tenant"]
    list_select_related = ["session", "tenant"]
    list_filter = [
        ("type", ChoicesDropdownFilter),
        ("severity", ChoicesDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["title"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())


@admin.register(Incident)
class IncidentAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["title", "type", "severity", "status_badge", "trip", "dispatcher_notified", "tenant"]
    list_select_related = ["trip", "tenant"]
    list_filter = [
        ("type", ChoicesDropdownFilter),
        ("severity", ChoicesDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("tenant", RelatedDropdownFilter),
    ]
    search_fields = ["title"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at"]
    actions = ["mark_as_resolved"]
    fieldsets = (
        ("Informations", {"fields": ("title", "type", "severity", "status")}),
        ("Contexte", {"fields": ("trip", "session", "reporter")}),
        ("Description", {"fields": ("description", "photos_urls", "gps_location", "gps_address")}),
        ("Suivi", {"fields": ("dispatcher_notified", "dispatcher_notified_at", "resolved_at")}),
        ("Métadonnées", {"fields": ("tenant", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        return render_status_badge(obj.status, obj.get_status_display())

    @action(description="Marquer résolu", icon="task_alt")
    def mark_as_resolved(self, request, queryset):
        """Passe les incidents sélectionnés au statut RESOLVED avec timestamp.

        Idempotent : les incidents déjà résolus ne sont pas touchés (leur
        resolved_at d'origine est préservé).
        """
        count = queryset.exclude(
            status=Incident.Status.RESOLVED,
        ).update(status=Incident.Status.RESOLVED, resolved_at=timezone.now())
        self.message_user(request, f"{count} incident(s) marqué(s) comme résolu(s).")


@admin.register(CashEntry)
class CashEntryAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["session", "reason", "amount_xof", "collected_by", "tenant"]
    list_select_related = ["session", "collected_by", "tenant"]
    list_filter = [("reason", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PassengerAccessLog)
class PassengerAccessLogAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["passenger", "context", "user", "ip_address", "created_at", "tenant"]
    list_select_related = ["passenger", "user", "tenant"]
    list_filter = [("context", ChoicesDropdownFilter), ("tenant", RelatedDropdownFilter)]
    date_hierarchy = "created_at"
    # PassengerAccessLog étend models.Model (pas TimestampMixin) : il a juste
    # created_at (auto_now_add). Pas d'updated_at. En lecture seule — c'est un
    # journal.
    readonly_fields = [f.name for f in PassengerAccessLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
