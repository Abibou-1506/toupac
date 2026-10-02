"""
TOUPAC IAM — Service de calcul des stats du dashboard admin.

Hors des callbacks pour rester testable sans client Django : un test unitaire
peut appeler `compute_stats(tenant)` directement, assertNumQueries dessus,
vérifier les valeurs sans monter un `request`.

Quatre stats, quatre queries. Chaque query est indexée (Trip sur
(tenant, departure_date), Order/Incident/Payment sur tenant).

Scoping :
- `tenant` passé : stats filtrées sur ce tenant.
- `tenant=None` : stats globales, tous tenants confondus (superadmin).

Pas de cache : volume d'appels très faible aujourd'hui, cache à ajouter
le jour où ce n'est plus vrai.
"""
from datetime import datetime, time

from django.db.models import Sum
from django.utils import timezone

from billing.models import Payment
from colis.models import Order
from voyage.models import Incident, Trip


def _month_bounds(now):
    """Retourne (start_of_month, start_of_next_month) en datetimes tz-aware.

    `now` est un datetime tz-aware en timezone locale (Africa/Dakar). On
    construit les bornes dans la même tz pour que « ce mois-ci » suive
    le calendrier local, pas UTC — un paiement encaissé le 1er à 00h30
    heure locale ne doit pas basculer sur « mois précédent » parce que
    UTC l'y range.
    """
    start = datetime.combine(
        now.date().replace(day=1), time.min, tzinfo=now.tzinfo,
    )
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1, tzinfo=now.tzinfo)
    else:
        next_month_start = datetime(
            now.year, now.month + 1, 1, tzinfo=now.tzinfo,
        )
    return start, next_month_start


def compute_stats(tenant):
    """
    Calcule les 4 stats du dashboard, scopées sur `tenant` ou globales.

    Args:
        tenant: iam.Tenant ou None. Si None, stats agrégées sur tous les
            tenants (vue superadmin).

    Returns:
        dict avec les quatre clés : trips_today, orders_in_progress,
        incidents_open, revenue_month_xof. Chaque valeur est un entier.
    """
    now = timezone.localtime()
    today = timezone.localdate()
    month_start, next_month_start = _month_bounds(now)

    def scoped(model):
        qs = model.objects.all()
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        return qs

    # Voyages aujourd'hui — filtrage sur departure_date seul, les voyages
    # annulés sont inclus (décision produit : « programmés aujourd'hui »,
    # pas « en cours »). Un filtre status != CANCELLED serait une seconde
    # décision produit, à ne pas glisser.
    trips_today = scoped(Trip).filter(departure_date=today).count()

    # Commandes en cours — DRAFT exclu (non engagé côté métier : ni contrat
    # ni prix signé), statuts terminaux (DELIVERED/FAILED/CANCELLED) exclus.
    # Seuls les 4 statuts intermédiaires actifs sont retenus.
    orders_in_progress = scoped(Order).filter(
        status__in=[
            Order.Status.CONFIRMED,
            Order.Status.DISPATCHED,
            Order.Status.PICKED_UP,
            Order.Status.IN_TRANSIT,
        ],
    ).count()

    # Incidents ouverts — exclude plutôt que filter __in : si un statut
    # est ajouté au modèle, cette ligne reste juste sans qu'on y pense.
    incidents_open = scoped(Incident).exclude(
        status=Incident.Status.RESOLVED,
    ).count()

    # CA du mois — somme des Payment success encaissés dans la fenêtre
    # [début du mois, début du mois suivant[, lue sur completed_at.
    # Choix Payment plutôt qu'Invoice.paid_at : une facture peut être
    # payée en plusieurs versements et paid_at ne capture que le dernier
    # — on perdrait les acomptes du mois courant payés sur une facture
    # clôturée au mois suivant. completed_at trace l'encaissement effectif.
    revenue = scoped(Payment).filter(
        status=Payment.Status.SUCCESS,
        completed_at__gte=month_start,
        completed_at__lt=next_month_start,
    ).aggregate(total=Sum("amount_xof"))["total"] or 0

    return {
        "trips_today": trips_today,
        "orders_in_progress": orders_in_progress,
        "incidents_open": incidents_open,
        "revenue_month_xof": revenue,
    }
