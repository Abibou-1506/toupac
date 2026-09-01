"""TOUPAC Voyage — Configuration Django Admin + unfold."""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

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
class LuggagePolicyAdmin(ModelAdmin):
    list_display = ["name", "included_kg", "max_kg", "excess_price_per_kg_xof", "max_pieces", "tenant"]
    list_filter = ["tenant"]
    search_fields = ["name"]


@admin.register(Route)
class RouteAdmin(ModelAdmin):
    list_display = ["name", "code", "origin_place", "destination_place", "distance_km", "is_active", "tenant"]
    list_filter = ["is_active", "tenant"]
    search_fields = ["name", "code"]
    inlines = [RouteStopInline]


@admin.register(Schedule)
class ScheduleAdmin(ModelAdmin):
    list_display = ["route", "departure_time", "default_vehicle_type", "default_price_xof", "is_active", "tenant"]
    list_filter = ["is_active", "route", "tenant"]


@admin.register(SeatMap)
class SeatMapAdmin(ModelAdmin):
    list_display = ["name", "vehicle_type", "total_seats", "tenant"]
    list_filter = ["vehicle_type", "tenant"]


@admin.register(Trip)
class TripAdmin(ModelAdmin):
    list_display = ["internal_id", "route", "departure_date", "status", "booked_seats", "total_seats", "vehicle", "driver"]
    list_filter = ["status", "departure_date", "route", "tenant"]
    search_fields = ["internal_id"]
    inlines = [TripStopInline]


@admin.register(Passenger)
class PassengerAdmin(ModelAdmin):
    list_display = ["first_name", "last_name", "phone", "email", "nationality", "tenant"]
    list_filter = ["nationality", "tenant"]
    search_fields = ["first_name", "last_name", "phone", "email", "id_number"]


@admin.register(Reservation)
class ReservationAdmin(ModelAdmin):
    list_display = ["trip", "passenger", "seat_label", "status", "amount_xof", "payment_method"]
    list_filter = ["status", "payment_method", "sales_channel", "tenant"]
    search_fields = ["seat_label", "passenger__first_name", "passenger__last_name"]


@admin.register(Controller)
class ControllerAdmin(ModelAdmin):
    list_display = ["user", "matricule", "agency", "score_conformity", "total_trips", "status", "tenant"]
    list_filter = ["status", "tenant"]
    search_fields = ["matricule", "user__first_name", "user__last_name"]


@admin.register(ControlSession)
class ControlSessionAdmin(ModelAdmin):
    list_display = ["trip", "controller", "opened_at", "closed_at", "sync_state", "tenant"]
    list_filter = ["sync_state", "tenant"]


@admin.register(ControlEvent)
class ControlEventAdmin(ModelAdmin):
    list_display = ["session", "event_type", "status", "created_at_local", "processed_at", "tenant"]
    list_filter = ["status", "event_type", "tenant"]


@admin.register(Anomaly)
class AnomalyAdmin(ModelAdmin):
    list_display = ["title", "type", "severity", "status", "session", "tenant"]
    list_filter = ["type", "severity", "status", "tenant"]
    search_fields = ["title"]


@admin.register(Incident)
class IncidentAdmin(ModelAdmin):
    list_display = ["title", "type", "severity", "status", "trip", "dispatcher_notified", "tenant"]
    list_filter = ["type", "severity", "status", "tenant"]
    search_fields = ["title"]


@admin.register(CashEntry)
class CashEntryAdmin(ModelAdmin):
    list_display = ["session", "reason", "amount_xof", "collected_by", "tenant"]
    list_filter = ["reason", "tenant"]


@admin.register(PassengerAccessLog)
class PassengerAccessLogAdmin(ModelAdmin):
    list_display = ["passenger", "context", "user", "ip_address", "created_at", "tenant"]
    list_filter = ["context", "tenant"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
