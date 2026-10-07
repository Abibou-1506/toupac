"""
Commande de rattrapage des TripStop manquants.

Le signal post_save(sender=Trip) materialise les TripStop a chaque creation
Trip depuis le 7 oct 2026 (commit d1c9c7b). Pour les Trips historiques crees
avant, cette commande applique la meme logique en bulk. Idempotente.
"""
from django.core.management.base import BaseCommand, CommandError

from iam.models import Tenant
from voyage.models import Trip
from voyage.services.trip_stops import materialize_trip_stops


class Command(BaseCommand):
    help = (
        "Materialise les TripStop manquants des Trips historiques crees avant "
        "le signal post_save du 7 oct 2026. Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", default=False,
            help="Compte sans ecrire.",
        )
        parser.add_argument(
            "--tenant", type=str, default=None,
            help="Restreint aux Trips d'un tenant par son slug.",
        )
        parser.add_argument(
            "--verbose", action="store_true", default=False,
            help="Liste chaque Trip materialise (internal_id + nombre de stops).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        tenant_slug = options["tenant"]
        verbose = options["verbose"]

        qs = Trip.objects.filter(stops__isnull=True)
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant '{tenant_slug}' introuvable.") from None
            qs = qs.filter(tenant=tenant)

        count = qs.count()
        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f"[dry-run] {count} Trip(s) a materialiser."
            ))
            return

        trips_done = 0
        stops_total = 0
        for trip in qs.iterator():
            created = materialize_trip_stops(trip)
            if created > 0:
                trips_done += 1
                stops_total += created
                if verbose:
                    self.stdout.write(
                        f"  {trip.internal_id} ({trip.tenant.slug}) : "
                        f"{created} stops crees"
                    )

        self.stdout.write(self.style.SUCCESS(
            f"{trips_done} Trip(s) materialise(s) ({stops_total} stops crees au total)."
        ))
