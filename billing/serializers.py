"""TOUPAC Billing — Serializers DRF."""
from rest_framework import serializers
from .models import Invoice, InvoiceLine, Payment, PriceList, PriceRule


class PriceRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceRule
        fields = "__all__"


class PriceListSerializer(serializers.ModelSerializer):
    rules = PriceRuleSerializer(many=True, read_only=True)

    class Meta:
        model = PriceList
        fields = "__all__"


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = "__all__"


class InvoiceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "invoice_number", "customer_name", "total_xof", "status", "issue_date", "paid_at"]


class InvoiceDetailSerializer(InvoiceListSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + [
            "customer_id", "customer_type", "due_date", "subtotal_xof", "tax_xof",
            "currency", "metadata", "created_by", "created_at", "updated_at", "lines",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"


class PaymentInitiateSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=Payment.Provider.choices)
    amount_xof = serializers.IntegerField(min_value=1)
    reservation_id = serializers.UUIDField(required=False, allow_null=True)
    order_id = serializers.UUIDField(required=False, allow_null=True)
    customer_phone = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        reservation_id = attrs.get("reservation_id")
        order_id = attrs.get("order_id")
        if bool(reservation_id) == bool(order_id):
            raise serializers.ValidationError(
                "Fournir exactement un de reservation_id ou order_id."
            )
        return attrs


class PricingCalculateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=PriceList.Type.choices)
    route_id = serializers.UUIDField(required=False, allow_null=True)
    pickup_place_id = serializers.UUIDField(required=False, allow_null=True)
    dropoff_place_id = serializers.UUIDField(required=False, allow_null=True)
    weight_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)
