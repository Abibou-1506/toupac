"""
TOUPAC Colis — Services métier : dispatch et génération d'identifiants.

DispatchService est un mock volontairement simple : il crée les DeliveryTasks
sans optimisation de tournée. L'intégration VROOM (VRP) / OSRM (distances,
géométrie de trajet) est prévue au Sprint 6 — cf. Architecture §3.5 Flux 3.
"""
import random
import string

from django.utils import timezone

from .models import DeliveryTask, Order, Parcel


class DispatchService:
    """Affecte des commandes confirmées à un chauffeur et un véhicule."""

    @staticmethod
    def dispatch_orders(tenant, order_ids, driver_id, vehicle_id):
        """
        Crée une task pickup + une task delivery pour chaque order, assignées
        au driver/vehicle donnés, et passe les orders en status "dispatched".

        V1 (mock) : l'ordre de tournée est simplement l'ordre des order_ids
        reçus — aucune optimisation géographique. V2 (Sprint 6) : VROOM.
        """
        orders = list(Order.objects.filter(tenant=tenant, id__in=order_ids))
        orders_by_id = {str(order.id): order for order in orders}

        tasks = []
        for index, order_id in enumerate(order_ids):
            order = orders_by_id.get(str(order_id))
            if order is None:
                continue

            pickup_task = DeliveryTask.objects.create(
                tenant=tenant,
                order=order,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                type=DeliveryTask.TaskType.PICKUP,
                place=order.pickup_place,
                sequence_order=index * 2,
            )
            delivery_task = DeliveryTask.objects.create(
                tenant=tenant,
                order=order,
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                type=DeliveryTask.TaskType.DELIVERY,
                place=order.dropoff_place,
                sequence_order=index * 2 + 1,
            )
            tasks.extend([pickup_task, delivery_task])

            order.status = Order.Status.DISPATCHED
            order.save(update_fields=["status", "updated_at"])

        return tasks


class TrackingNumberGenerator:
    """Génère des numéros de suivi uniques au format TPC-XXXXXXXXXX."""

    @staticmethod
    def generate():
        while True:
            number = "TPC-" + "".join(random.choices(string.digits, k=10))
            if not Parcel.objects.filter(tracking_number=number).exists():
                return number


class InternalIdGenerator:
    """Génère des identifiants de commande au format CMD-YYYY-NNNN."""

    @staticmethod
    def generate(tenant):
        year = timezone.now().year
        last = Order.objects.filter(
            tenant=tenant, internal_id__startswith=f"CMD-{year}-",
        ).order_by("-internal_id").first()
        if last:
            seq = int(last.internal_id.split("-")[-1]) + 1
        else:
            seq = 1
        return f"CMD-{year}-{seq:04d}"
