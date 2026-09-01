"""TOUPAC Billing — ViewSets et vues DRF."""
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Invoice, Payment, PriceList
from .serializers import (
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    PaymentInitiateSerializer,
    PriceListSerializer,
    PricingCalculateSerializer,
)
from .services import PricingEngine

_TAG = extend_schema(tags=["Billing"])
_CRUD_TAGS = {
    "list": _TAG, "retrieve": _TAG, "create": _TAG,
    "update": _TAG, "partial_update": _TAG, "destroy": _TAG,
}


@extend_schema_view(**_CRUD_TAGS)
class PriceListViewSet(viewsets.ModelViewSet):
    serializer_class = PriceListSerializer
    queryset = PriceList.objects.none()
    filterset_fields = ["type", "is_active"]

    def get_queryset(self):
        return PriceList.objects.filter(tenant=self.request.tenant).prefetch_related("rules")


@extend_schema_view(**_CRUD_TAGS)
class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.none()
    filterset_fields = ["status"]
    search_fields = ["invoice_number", "customer_name"]
    ordering = ["-issue_date"]

    def get_queryset(self):
        return Invoice.objects.filter(tenant=self.request.tenant).prefetch_related("lines")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InvoiceDetailSerializer
        return InvoiceListSerializer


@extend_schema(
    tags=["Billing"],
    request=PaymentInitiateSerializer,
    responses=inline_serializer("PaymentInitiateResponse", {
        "payment_id": serializers.CharField(),
        "provider_tx_id": serializers.CharField(required=False),
        "redirect_url": serializers.CharField(required=False),
        "status": serializers.CharField(),
        "error": serializers.CharField(required=False),
    }),
)
class PaymentInitiateView(APIView):
    """POST /api/v1/billing/payments/initiate/ — lance un paiement mobile money."""
    throttle_scope = "payment_initiate"

    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = Payment.objects.create(
            tenant=request.tenant,
            provider=data["provider"],
            amount_xof=data["amount_xof"],
            reservation_id=data.get("reservation_id"),
            order_id=data.get("order_id"),
            status=Payment.Status.INITIATED,
        )

        from billing.providers.intouch import IntouchProvider
        provider = IntouchProvider()  # V1 : uniquement Intouch
        callback_url = request.build_absolute_uri("/api/v1/billing/payments/webhook/")

        result = provider.initiate_payment(
            amount=data["amount_xof"],
            currency="XOF",
            description=data.get("description") or f"Paiement TOUPAC #{payment.id}",
            customer_phone=data["customer_phone"],
            callback_url=callback_url,
            metadata={"payment_id": str(payment.id)},
        )

        if result.success:
            payment.provider_tx_id = result.provider_tx_id
            payment.status = Payment.Status.PENDING
            payment.provider_response = result.raw_response
            payment.save()
            return Response({
                "payment_id": str(payment.id),
                "provider_tx_id": result.provider_tx_id,
                "redirect_url": result.redirect_url,
                "status": "pending",
            }, status=status.HTTP_201_CREATED)

        payment.status = Payment.Status.FAILED
        payment.failure_reason = result.error_message
        payment.save()
        return Response({
            "payment_id": str(payment.id),
            "status": "failed",
            "error": result.error_message,
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Billing"],
    request=inline_serializer("PaymentWebhookRequest", {
        "cpm_site_id": serializers.CharField(required=False),
        "partner_id": serializers.CharField(required=False),
        "partner_transaction_id": serializers.CharField(required=False),
        "provider_tx_id": serializers.CharField(required=False),
    }),
    responses=inline_serializer("PaymentWebhookResponse", {"status": serializers.CharField()}),
)
class PaymentWebhookView(APIView):
    """POST /api/v1/billing/payments/webhook/ — callback du provider mobile money. Public."""
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        from billing.providers.intouch import IntouchProvider
        provider = IntouchProvider()

        if not provider.verify_callback(request.data, request.headers):
            return Response({"detail": "Signature invalide."}, status=status.HTTP_403_FORBIDDEN)

        tx_id = request.data.get("partner_transaction_id") or request.data.get("provider_tx_id", "")
        payment = Payment.objects.filter(provider_tx_id=tx_id).first()
        if not payment:
            return Response({"detail": "Transaction inconnue."}, status=status.HTTP_404_NOT_FOUND)

        tx_status = provider.get_transaction_status(tx_id)
        if tx_status == "success":
            payment.status = Payment.Status.SUCCESS
            payment.completed_at = timezone.now()
            payment.save()
            if payment.reservation_id:
                from voyage.models import Reservation
                Reservation.objects.filter(id=payment.reservation_id).update(
                    payment_ref=tx_id, status="checked_in",
                )
            elif payment.order_id:
                from colis.models import Order
                Order.objects.filter(id=payment.order_id).update(payment_status="paid")
        elif tx_status == "failed":
            payment.status = Payment.Status.FAILED
            payment.failure_reason = request.data.get("message", "Échec paiement")
            payment.save()

        return Response({"status": "received"})


@extend_schema(
    tags=["Billing"],
    request=PricingCalculateSerializer,
    responses=inline_serializer("PricingCalculateResponse", {
        "price_xof": serializers.IntegerField(required=False),
        "currency": serializers.CharField(required=False),
        "detail": serializers.CharField(required=False),
    }),
)
class PricingCalculateView(APIView):
    """POST /api/v1/billing/pricing/calculate/ — simulation de tarif."""

    def post(self, request):
        serializer = PricingCalculateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            if data["type"] == "voyage":
                price = PricingEngine.calculate_voyage_price(
                    tenant=request.tenant, route_id=data.get("route_id"),
                )
            else:
                price = PricingEngine.calculate_colis_price(
                    tenant=request.tenant,
                    pickup_place_id=data.get("pickup_place_id"),
                    dropoff_place_id=data.get("dropoff_place_id"),
                    weight_kg=data.get("weight_kg"),
                )
            return Response({"price_xof": price, "currency": "XOF"})
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
