"""
TOUPAC Voyage — Résumé agrégé d'un voyage, écrit à la fermeture d'une session.

`Trip.summary` existe depuis le port Sprint 2 et n'était jamais renseigné. Ce
module calcule son contenu à partir des `Reservation` et des `CashEntry` du
trip. Appelé à chaque fermeture de `ControlSession` par la vue
`TripViewSet.control_close` — pas par un signal, décision explicite : un
signal porterait la mécanique dans un fichier que personne ne regarde quand il
débogue la clôture, alors que celle-ci est son seul déclencheur.

Un trip peut avoir plusieurs sessions successives — un contrôleur relevé à
l'escale, par exemple. Le `summary` est donc **recalculé en entier** à chaque
clôture, pas accumulé : il reflète l'état courant du voyage, pas la session qui
vient de fermer. Rejouer la fonction est idempotent.
"""
from django.db.models import Count, Q, Sum
from django.utils import timezone


def build_trip_summary(trip):
    """
    Agrégat de fin de voyage sous forme JSON-sérialisable, prêt à écrire sur
    `Trip.summary`.

    Les clés sont figées — l'app admin et les tests s'y appuient — et portent
    toutes une valeur par défaut (zéro, chaîne vide), jamais `None` : lire un
    champ absent ne doit pas forcer un `coalesce` côté lecteur. `revenue_xof`
    ne compte que les sièges effectivement embarqués ; `cash_xof` compte toutes
    les écritures de caisse du trip, qui peuvent couvrir des opérations
    périphériques (régulation).
    """
    # Imports locaux : ce module est chargé par la vue, qui est elle-même
    # chargée par URLs — importer les modèles au niveau du fichier déclencherait
    # un cycle d'imports à l'initialisation.
    from voyage.models import CashEntry, Reservation

    reservations = Reservation.objects.filter(tenant=trip.tenant, trip=trip)
    stats = reservations.aggregate(
        boarded=Count("id", filter=Q(status=Reservation.Status.BOARDED)),
        no_show=Count("id", filter=Q(status=Reservation.Status.NO_SHOW)),
        refused=Count("id", filter=Q(status=Reservation.Status.REFUSED)),
        onboard_sales=Count("id", filter=Q(sales_channel="onboard")),
        revenue_xof=Sum(
            "amount_xof", filter=Q(status=Reservation.Status.BOARDED),
        ),
    )
    cash_total = (
        CashEntry.objects.filter(tenant=trip.tenant, session__trip=trip)
        .aggregate(total=Sum("amount_xof"))["total"]
    )

    return {
        "updated_at": timezone.now().isoformat(),
        "boarded": stats["boarded"] or 0,
        "no_show": stats["no_show"] or 0,
        "refused": stats["refused"] or 0,
        "onboard_sales": stats["onboard_sales"] or 0,
        "revenue_xof": stats["revenue_xof"] or 0,
        "cash_xof": cash_total or 0,
    }
