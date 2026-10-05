"""Endpoints d'agrégation pour le Dashboard backoffice.

Ces vues sont transverses (voyage + colis + billing), donc hébergées
dans `core/` plutôt que dans un domaine particulier. Si le périmètre
dashboard grandit (plus de widgets, personnalisation par rôle), elles
pourront être extraites dans une app `dashboard/` dédiée.

Les clés de réponse sont en camelCase pour matcher directement les
types TypeScript du front sans adaptateur runtime (cf. DECISIONS.md
« Mapping backend ↔ front toupac-web »).
"""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Payment
from colis.models import Order
from voyage.models import Incident, Reservation, Trip


class DashboardKPIsView(APIView):
    """GET /api/v1/dashboard/kpis/ — 4 cards du haut du Dashboard."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Dashboard"], responses={200: None})
    def get(self, request):
        tenant = request.tenant
        if tenant is None:
            return Response({"detail": "Tenant requis."}, status=400)

        now = timezone.now()
        today = now.date()
        yesterday = today - timedelta(days=1)
        month_start = today.replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        seven_days_ago = now - timedelta(days=7)

        # ─── 1. Voyages aujourd'hui ───
        trips_today = Trip.objects.filter(
            tenant=tenant, departure_date=today,
        ).count()
        trips_yesterday = Trip.objects.filter(
            tenant=tenant, departure_date=yesterday,
        ).count()
        delta_trips = trips_today - trips_yesterday
        if delta_trips > 0:
            trips_trend = f"+{delta_trips} vs hier"
            trips_tone = "success"
        elif delta_trips < 0:
            trips_trend = f"{delta_trips} vs hier"
            trips_tone = "warning"
        else:
            trips_trend = "stable vs hier"
            trips_tone = "neutral"

        # ─── 2. Commandes en cours ───
        # In-progress = confirmed → in_transit (ni delivered ni cancelled ni failed).
        in_progress_statuses = [
            Order.Status.CONFIRMED,
            Order.Status.DISPATCHED,
            Order.Status.PICKED_UP,
            Order.Status.IN_TRANSIT,
        ]
        orders_in_progress = Order.objects.filter(
            tenant=tenant, status__in=in_progress_statuses,
        )
        orders_count = orders_in_progress.count()
        in_transit = orders_in_progress.filter(status=Order.Status.IN_TRANSIT).count()
        to_deliver = orders_in_progress.filter(
            status__in=[Order.Status.DISPATCHED, Order.Status.PICKED_UP],
        ).count()
        orders_trend = f"{in_transit} en transit, {to_deliver} à livrer"
        orders_tone = "neutral"

        # ─── 3. Incidents ouverts (7 derniers jours, non résolus) ───
        incidents_open = Incident.objects.filter(
            tenant=tenant, created_at__gte=seven_days_ago,
        ).exclude(status=Incident.Status.RESOLVED)
        incidents_count = incidents_open.count()
        incidents_critical = incidents_open.filter(
            severity=Incident.Severity.CRITICAL,
        ).count()
        if incidents_critical > 0:
            s = "s" if incidents_critical > 1 else ""
            incidents_trend = f"{incidents_critical} critique{s}"
            incidents_tone = "danger"
        elif incidents_count > 0:
            incidents_trend = "aucun critique"
            incidents_tone = "warning"
        else:
            incidents_trend = "aucun incident ouvert"
            incidents_tone = "success"

        # ─── 4. CA du mois ───
        # Somme des Reservation.amount_xof (BOARDED) + Order.total_amount_xof
        # (DELIVERED) créées pendant la période. Les Payment ne sont pas
        # réagrégés ici : la source de vérité du revenu reconnu est la
        # réservation embarquée / la commande livrée, pas la transaction
        # mobile money (qui peut avoir été initiée sans aboutir).
        revenue_month = _month_revenue(tenant, month_start, today)
        last_revenue_month = _month_revenue(tenant, last_month_start, last_month_end)

        if last_revenue_month > 0:
            pct = round(((revenue_month - last_revenue_month) / last_revenue_month) * 100)
            if pct > 0:
                revenue_trend = f"+{pct} % vs mois dernier"
                revenue_tone = "success"
            elif pct < 0:
                revenue_trend = f"{pct} % vs mois dernier"
                revenue_tone = "warning"
            else:
                revenue_trend = "stable vs mois dernier"
                revenue_tone = "neutral"
        elif revenue_month > 0:
            revenue_trend = "premier mois d'activité"
            revenue_tone = "neutral"
        else:
            revenue_trend = "aucun CA"
            revenue_tone = "neutral"

        return Response({
            "voyagesAujourdhui": {
                "value": trips_today,
                "trend": trips_trend,
                "trendTone": trips_tone,
            },
            "commandesEnCours": {
                "value": orders_count,
                "trend": orders_trend,
                "trendTone": orders_tone,
            },
            "incidentsOuverts": {
                "value": incidents_count,
                "trend": incidents_trend,
                "trendTone": incidents_tone,
            },
            "caDuMois": {
                "value": revenue_month,
                "trend": revenue_trend,
                "trendTone": revenue_tone,
            },
        })


def _month_revenue(tenant, start_date, end_date):
    """Somme Reservation(BOARDED).amount_xof + Order(DELIVERED).total_amount_xof
    sur la période [start_date, end_date] inclus. Retourne un int."""
    revenue_voyage = Reservation.objects.filter(
        tenant=tenant,
        status=Reservation.Status.BOARDED,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).aggregate(total=Sum("amount_xof"))["total"] or 0

    revenue_colis = Order.objects.filter(
        tenant=tenant,
        status=Order.Status.DELIVERED,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).aggregate(total=Sum("total_amount_xof"))["total"] or 0

    return revenue_voyage + revenue_colis


class DashboardActivitiesView(APIView):
    """GET /api/v1/dashboard/activities/ — feed d'activité récente.

    Agrège les 10 derniers événements par source (voyages démarrés,
    paiements success, incidents, commandes livrées, réservations créées),
    puis garde les 20 plus récentes triées par timestamp DESC.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Dashboard"], responses={200: None})
    def get(self, request):
        tenant = request.tenant
        if tenant is None:
            return Response({"detail": "Tenant requis."}, status=400)

        limit_per_source = 10
        activities = []

        for trip in (
            Trip.objects.filter(tenant=tenant, actual_departure_at__isnull=False)
            .select_related("route")
            .order_by("-actual_departure_at")[:limit_per_source]
        ):
            activities.append({
                "id": f"trip-start-{trip.id}",
                "type": "voyage",
                "description": f"Voyage {trip.internal_id} démarré · {trip.route.name}",
                "timestamp": trip.actual_departure_at.isoformat(),
                "linkTo": f"/voyages/{trip.id}",
            })

        for payment in (
            Payment.objects.filter(
                tenant=tenant,
                status=Payment.Status.SUCCESS,
                completed_at__isnull=False,
            )
            .order_by("-completed_at")[:limit_per_source]
        ):
            provider_label = payment.get_provider_display()
            amount_formatted = f"{payment.amount_xof:,}".replace(",", " ")
            activities.append({
                "id": f"payment-{payment.id}",
                "type": "paiement",
                "description": f"Paiement reçu · {amount_formatted} XOF via {provider_label}",
                "timestamp": payment.completed_at.isoformat(),
                "linkTo": "/paiements",
            })

        for incident in (
            Incident.objects.filter(tenant=tenant)
            .select_related("trip")
            .order_by("-created_at")[:limit_per_source]
        ):
            is_resolved = incident.status == Incident.Status.RESOLVED
            status_label = "résolu" if is_resolved else "signalé"
            activities.append({
                "id": f"incident-{incident.id}",
                "type": "incident",
                "description": f"Incident {status_label} · {incident.title}",
                "timestamp": incident.created_at.isoformat(),
                "linkTo": "/incidents",
            })

        for order in (
            Order.objects.filter(tenant=tenant, status=Order.Status.DELIVERED)
            .order_by("-updated_at")[:limit_per_source]
        ):
            activities.append({
                "id": f"order-delivered-{order.id}",
                "type": "commande",
                "description": f"Commande {order.internal_id} livrée",
                "timestamp": order.updated_at.isoformat(),
                "linkTo": f"/commandes/{order.id}",
            })

        for reservation in (
            Reservation.objects.filter(tenant=tenant)
            .select_related("trip__route")
            .order_by("-created_at")[:limit_per_source]
        ):
            route_name = (
                reservation.trip.route.name
                if reservation.trip and reservation.trip.route
                else "—"
            )
            activities.append({
                "id": f"reservation-{reservation.id}",
                "type": "reservation",
                "description": f"Nouvelle réservation · {route_name}",
                "timestamp": reservation.created_at.isoformat(),
                "linkTo": None,
            })

        activities.sort(key=lambda a: a["timestamp"], reverse=True)
        return Response(activities[:20])
