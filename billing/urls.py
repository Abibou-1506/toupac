from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    InvoiceViewSet, PaymentInitiateView, PaymentWebhookView, PriceListViewSet,
    PricingCalculateView,
)

router = DefaultRouter()
router.register("price-lists", PriceListViewSet, basename="price-list")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("payments/initiate/", PaymentInitiateView.as_view(), name="payments-initiate"),
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payments-webhook"),
    path("pricing/calculate/", PricingCalculateView.as_view(), name="pricing-calculate"),
] + router.urls
