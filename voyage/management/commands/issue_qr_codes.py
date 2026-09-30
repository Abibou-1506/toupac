"""Émet (ou ré-émet) les QR des réservations d'un voyage — outil de dev."""
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from voyage.models import Reservation, Trip


class Command(BaseCommand):
    help = "Signe les billets d'un voyage et exporte les QR en PNG."

    def add_arguments(self, parser):
        parser.add_argument("--trip", required=True, help="UUID du voyage, ou internal_id")
        parser.add_argument("--tenant", help="Slug du tenant — lève l'ambiguïté sur internal_id")
        parser.add_argument("--out", default="qr_out")
        parser.add_argument("--force", action="store_true",
                            help="Ré-émet même les billets déjà signés. INVALIDE les QR déjà distribués.")

    def _resolve_trip(self, value, tenant_slug):
        try:
            return Trip.objects.get(pk=uuid.UUID(value))
        except ValueError:
            pass                      # pas un UUID : on tente l'internal_id
        except Trip.DoesNotExist:
            raise CommandError(f"Aucun voyage avec l'id {value}.") from None

        qs = Trip.objects.filter(internal_id=value).select_related("tenant")
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)

        # internal_id n'est unique QUE par tenant : sans désambiguïsation on
        # signerait les billets d'une autre compagnie sans s'en apercevoir.
        matches = list(qs[:5])
        if not matches:
            raise CommandError(f"Aucun voyage nommé {value}.")
        if len(matches) > 1:
            lignes = "\n".join(f"  {t.pk}  {t.tenant.slug}  {t.departure_date}" for t in matches)
            raise CommandError(
                f"{len(matches)} voyages nommés {value}. Précise --tenant, ou passe l'UUID :\n{lignes}"
            )
        return matches[0]

    def handle(self, *args, **options):
        from voyage.services.qr_jwt import sign_ticket_jwt

        trip = self._resolve_trip(options["trip"], options.get("tenant"))
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)

        try:
            import qrcode
        except ImportError:
            qrcode = None
            self.stderr.write("qrcode absent — tokens affichés, pas de PNG.")

        reservations = Reservation.objects.filter(
            tenant=trip.tenant, trip=trip,
            status__in=[Reservation.Status.BOOKED, Reservation.Status.CHECKED_IN],
        ).select_related("passenger", "trip")

        signed = skipped = 0
        for reservation in reservations:
            if reservation.qr_code_jwt and not options["force"]:
                skipped += 1
                token = reservation.qr_code_jwt
            else:
                token = sign_ticket_jwt(reservation)
                reservation.qr_code_jwt = token
                reservation.save(update_fields=["qr_code_jwt"])
                signed += 1

            self.stdout.write(f"{reservation.seat_label}\t{reservation.id}")
            if qrcode is not None:
                qrcode.make(token).save(out / f"{trip.internal_id}_{reservation.seat_label}.png")

        self.stdout.write(self.style.SUCCESS(
            f"{trip.internal_id} ({trip.tenant.slug}) — {signed} signé(s), "
            f"{skipped} déjà signé(s) réexporté(s) — {out.resolve()}"
        ))
