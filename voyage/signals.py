"""
TOUPAC Voyage — Signaux.

Les escales d'un voyage sont dérivées de sa route : à la création d'un `Trip`,
on matérialise un `TripStop` par `RouteStop` ordonné de la route choisie.

Sans ça, la timeline des escales reste vide côté admin et côté backoffice web
tant qu'un contrôleur n'a pas remonté d'event `stop_arrive`/`stop_depart`,
alors que ces events supposent justement que le `TripStop` existe déjà
(`handle_stop_arrive` fait un `TripStop.objects.filter(id=stop_id)`).

Le signal couvre tous les chemins de création (DRF serializer, admin Django
ORM direct, `seed_demo`, scripts shell) — un `TripCreateSerializer.create()`
override aurait raté la création via admin et via management commands.

Idempotent : si des `TripStop` existent déjà pour ce voyage, on ne recrée
rien (seed_demo et admin peuvent écrire par-dessus sans double effet).
"""
from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver

from voyage.models import Trip, TripStop


@receiver(
    post_save,
    sender=Trip,
    dispatch_uid="voyage.materialize_tripstops_on_trip_creation",
)
def materialize_tripstops_on_trip_creation(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.stops.exists():
        return
    route_stops = instance.route.stops.order_by("stop_order")
    TripStop.objects.bulk_create([
        TripStop(
            tenant=instance.tenant,
            trip=instance,
            route_stop=rs,
            place=rs.place,
            stop_order=rs.stop_order,
            eta=instance.scheduled_at + timedelta(minutes=rs.arrival_offset_minutes),
            status=TripStop.Status.PENDING,
        )
        for rs in route_stops
    ])
