"""
TOUPAC Voyage — Signaux.

Deux hooks post_save sur `Trip` cohabitent via `dispatch_uid` distincts :

1. `materialize_tripstops_on_trip_creation` (création uniquement).
   Les escales d'un voyage sont dérivées de sa route : à la création d'un
   `Trip`, on matérialise un `TripStop` par `RouteStop` ordonné de la route
   choisie. Sans ça, la timeline des escales reste vide côté admin et côté
   backoffice web tant qu'un contrôleur n'a pas remonté d'event
   `stop_arrive`/`stop_depart`, alors que ces events supposent justement
   que le `TripStop` existe déjà (`handle_stop_arrive` fait un
   `TripStop.objects.filter(id=stop_id)`).
   Idempotent : si des `TripStop` existent déjà pour ce voyage, on ne
   recrée rien. La logique vit dans `voyage/services/trip_stops.py` —
   partagée avec la commande management `materialize_missing_tripstops`.

2. `cascade_reservations_on_trip_terminal` (transitions vers COMPLETED
   / CANCELLED). À la clôture d'un voyage, toutes les `Reservation`
   encore `BOOKED` deviennent `NO_SHOW` et les `CHECKED_IN` deviennent
   `BOARDED`. Les autres statuts (`BOARDED`, `NO_SHOW`, `REFUSED`,
   `CANCELLED`) ne sont jamais touchés — idempotence. Le pattern pre_save
   + attribut transient `_original_status` est le seul moyen de détecter
   la transition exacte : `post_save` seul ne sait pas quel était le
   statut avant.

Le signal couvre tous les chemins de mutation (DRF serializer, admin
Django ORM direct, batch mobile offline-sync, `seed_demo`, scripts shell,
Celery) — un hook dans la vue web aurait raté toutes ces sources.
"""
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from voyage.models import Reservation, Trip
from voyage.services.trip_stops import materialize_trip_stops

# Statuts terminaux du voyage qui déclenchent la cascade sur les réservations.
_TRIP_TERMINAL_STATUSES = {Trip.Status.COMPLETED, Trip.Status.CANCELLED}

# Mapping transition réservation → nouveau statut à la clôture du voyage.
# Choix du mapping `CHECKED_IN → BOARDED` : à la clôture d'un voyage, un
# passager scanné à l'embarquement sans trace ultérieure de refus est
# considéré monté. Pour durcir en mode sécurité, remplacer la valeur par
# `Reservation.Status.NO_SHOW`.
_RESERVATION_AUTO_TRANSITIONS = {
    Reservation.Status.BOOKED: Reservation.Status.NO_SHOW,
    Reservation.Status.CHECKED_IN: Reservation.Status.BOARDED,
}

# Dette V1.2 : le modèle `Reservation` possède `boarded_at` mais pas
# `no_show_at`. On remplit uniquement les timestamps qui existent — voir
# DETTES.md pour la trace. L'ajout est purement additif, un futur ticket
# pourra le reprendre sans toucher au signal.
_RESERVATION_STATUS_TIMESTAMPS = {
    Reservation.Status.BOARDED: "boarded_at",
    Reservation.Status.NO_SHOW: "no_show_at",
}


def _has_field(model, name):
    return any(f.name == name for f in model._meta.get_fields())


@receiver(
    post_save,
    sender=Trip,
    dispatch_uid="voyage.materialize_tripstops_on_trip_creation",
)
def materialize_tripstops_on_trip_creation(sender, instance, created, **kwargs):
    if not created:
        return
    materialize_trip_stops(instance)


@receiver(
    pre_save,
    sender=Trip,
    dispatch_uid="voyage.capture_original_trip_status",
)
def capture_original_trip_status(sender, instance, **kwargs):
    """Mémorise sur l'instance le statut DB courant pour que `post_save` sache
    s'il y a eu transition. Attribut transient (préfixe `_`) — jamais sérialisé
    ni persisté."""
    if instance.pk:
        instance._toupac_original_status = (
            Trip.objects.filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )
    else:
        instance._toupac_original_status = None


@receiver(
    post_save,
    sender=Trip,
    dispatch_uid="voyage.cascade_reservations_on_trip_terminal",
)
def cascade_reservations_on_trip_terminal(sender, instance, created, **kwargs):
    """Cascade terminal : BOOKED → NO_SHOW, CHECKED_IN → BOARDED.

    Idempotent : un trip déjà terminal qui est resauvegardé ne redéclenche
    pas la cascade (filtre sur `status=from_status` → queryset vide une fois
    la cascade passée).
    """
    if created:
        return
    original = getattr(instance, "_toupac_original_status", None)
    if original == instance.status:
        return
    if instance.status not in _TRIP_TERMINAL_STATUSES:
        return
    if original in _TRIP_TERMINAL_STATUSES:
        # Transition terminal → terminal (ex. COMPLETED resauvegardé avec
        # un autre update_fields) : déjà traité au premier passage terminal.
        return

    now = timezone.now()
    with transaction.atomic():
        for from_status, to_status in _RESERVATION_AUTO_TRANSITIONS.items():
            update_fields = {"status": to_status, "updated_at": now}
            ts_field = _RESERVATION_STATUS_TIMESTAMPS.get(to_status)
            if ts_field and _has_field(Reservation, ts_field):
                update_fields[ts_field] = now
            Reservation.objects.filter(
                trip=instance, status=from_status,
            ).update(**update_fields)
