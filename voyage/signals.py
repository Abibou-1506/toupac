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

La logique de matérialisation vit dans `voyage/services/trip_stops.py` —
partagée avec la commande management `materialize_missing_tripstops` qui
rattrape les Trips historiques créés avant ce signal.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from voyage.models import Trip
from voyage.services.trip_stops import materialize_trip_stops


@receiver(
    post_save,
    sender=Trip,
    dispatch_uid="voyage.materialize_tripstops_on_trip_creation",
)
def materialize_tripstops_on_trip_creation(sender, instance, created, **kwargs):
    if not created:
        return
    materialize_trip_stops(instance)
