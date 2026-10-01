"""TOUPAC Billing — Moteur de tarification et génération de factures."""
from decimal import Decimal

from django.utils import timezone

from .models import (
    CUSTOMER_TYPE_CLIENT_USER,
    CUSTOMER_TYPE_EXTERNAL,
    CUSTOMER_TYPE_PASSENGER,
    Invoice,
    InvoiceLine,
    PriceList,
    PriceRule,
)


class PricingEngine:
    """Calcul de tarif pour voyage et colis."""

    @staticmethod
    def calculate_voyage_price(tenant, route_id, origin_stop_id=None, destination_stop_id=None):
        """
        Retourne le prix en XOF pour un trajet voyage.

        1. Cherche une PriceRule active (grille voyage) pour la route.
        2. À défaut, retombe sur le default_price_xof du Schedule de la route.
        3. Sinon, lève ValueError.
        """
        rule = (
            PriceRule.objects.filter(
                tenant=tenant,
                price_list__type=PriceList.Type.VOYAGE,
                price_list__is_active=True,
                route_id=route_id,
            )
            .select_related("price_list")
            .first()
        )
        if rule is not None:
            return rule.base_amount_xof

        from voyage.models import Schedule

        schedule = (
            Schedule.objects.filter(tenant=tenant, route_id=route_id, is_active=True)
            .order_by("departure_time")
            .first()
        )
        if schedule is not None and schedule.default_price_xof:
            return schedule.default_price_xof

        raise ValueError("Aucun tarif configuré")

    @staticmethod
    def calculate_colis_price(tenant, pickup_place_id, dropoff_place_id, weight_kg=None):
        """
        Retourne le prix en XOF pour une livraison colis.

        1. Cherche une PriceRule active (grille colis).
        2. "fixed" → base_amount_xof.
        3. "per_kg" → base_amount_xof + weight_kg * rate_per_unit, borné par
           min/max_amount_xof si définis.
        4. Toute autre méthode → ValueError (non supportée pour l'instant).
        """
        rule = (
            PriceRule.objects.filter(
                tenant=tenant,
                price_list__type=PriceList.Type.COLIS,
                price_list__is_active=True,
            )
            .select_related("price_list")
            .first()
        )
        if rule is None:
            raise ValueError("Aucun tarif configuré")

        if rule.calculation_method == PriceRule.CalculationMethod.FIXED:
            price = rule.base_amount_xof
        elif rule.calculation_method == PriceRule.CalculationMethod.PER_KG:
            weight = Decimal(str(weight_kg)) if weight_kg else Decimal("0")
            rate = rule.rate_per_unit or Decimal("0")
            price = rule.base_amount_xof + int(weight * rate)
        else:
            raise ValueError("Méthode de calcul non supportée")

        if rule.min_amount_xof is not None:
            price = max(price, rule.min_amount_xof)
        if rule.max_amount_xof is not None:
            price = min(price, rule.max_amount_xof)
        return price


class InvoiceGenerator:
    """Génère des factures à partir de réservations ou de commandes."""

    @staticmethod
    def generate_invoice_number(tenant):
        """Format FAC-YYYY-NNNN, séquentiel par tenant."""
        year = timezone.now().year
        last = Invoice.objects.filter(
            tenant=tenant, invoice_number__startswith=f"FAC-{year}-",
        ).order_by("-invoice_number").first()
        seq = int(last.invoice_number.split("-")[-1]) + 1 if last else 1
        return f"FAC-{year}-{seq:04d}"

    @staticmethod
    def from_reservation(reservation):
        """
        Crée une facture pour une réservation de voyage.

        Deux chemins selon le rattachement du passager. Si sa fiche porte un
        `customer_user`, la facture pointe sur ce compte (`client_user`) — c'est
        ce lien que `/customer/my-payments/` suit, et sans lui le client ne
        retrouverait aucun de ses règlements. Sans compte rattaché, la facture
        pointe sur la fiche passager (`passenger`), seule référence identifiante
        d'un voyageur occasionnel.

        Avant le 1er oct 2026, ce handler écrivait `"passenger"` dans tous les
        cas — y compris pour un passager rattaché à un compte client. Le
        couple `(customer_id, customer_type)` ne correspondait alors à aucune
        branche du filtre de la vue, et les paiements d'un client inscrit
        restaient invisibles dans son espace.
        """
        passenger = reservation.passenger
        if passenger.customer_user_id:
            customer_type = CUSTOMER_TYPE_CLIENT_USER
            customer_id = passenger.customer_user_id
        else:
            customer_type = CUSTOMER_TYPE_PASSENGER
            customer_id = passenger.id

        invoice = Invoice.objects.create(
            tenant=reservation.tenant,
            invoice_number=InvoiceGenerator.generate_invoice_number(reservation.tenant),
            customer_name=passenger.full_name,
            customer_type=customer_type,
            customer_id=customer_id,
            issue_date=timezone.now().date(),
            subtotal_xof=reservation.amount_xof,
            tax_xof=0,
            total_xof=reservation.amount_xof,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description=f"Billet {reservation.trip.route.name} — siège {reservation.seat_label}",
            reference_type="reservation",
            reference_id=reservation.id,
            quantity=1,
            unit_price_xof=reservation.amount_xof,
            amount_xof=reservation.amount_xof,
        )
        return invoice

    @staticmethod
    def from_order(order):
        """
        Crée une facture pour une commande colis.

        Avant le 1er oct 2026, cette méthode écrivait `"user"` quand la
        commande portait un `customer` — valeur qui n'appartenait à aucune
        branche de la convention `customer_type`. Alignée désormais sur
        `client_user`, en cohérence avec `from_reservation`. Sans `customer`,
        la facture reste externe, `customer_id` à nul : il n'y a pas
        d'identifiant exploitable pour la retrouver depuis l'espace client.
        """
        if order.customer_id:
            customer_type = CUSTOMER_TYPE_CLIENT_USER
            customer_id = order.customer_id
        else:
            customer_type = CUSTOMER_TYPE_EXTERNAL
            customer_id = None

        invoice = Invoice.objects.create(
            tenant=order.tenant,
            invoice_number=InvoiceGenerator.generate_invoice_number(order.tenant),
            customer_name=order.customer_name or (order.customer.full_name if order.customer else "Client"),
            customer_type=customer_type,
            customer_id=customer_id,
            issue_date=timezone.now().date(),
            subtotal_xof=order.total_amount_xof or 0,
            tax_xof=0,
            total_xof=order.total_amount_xof or 0,
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description=f"Livraison {order.internal_id}",
            reference_type="order",
            reference_id=order.id,
            quantity=1,
            unit_price_xof=order.total_amount_xof or 0,
            amount_xof=order.total_amount_xof or 0,
        )
        return invoice
