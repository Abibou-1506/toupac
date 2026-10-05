from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    InvoiceViewSet,
    PaymentInitiateView,
    PaymentViewSet,
    PaymentWebhookView,
    PriceListViewSet,
    PricingCalculateView,
)

router = DefaultRouter()
router.register("price-lists", PriceListViewSet, basename="price-list")
router.register("invoices", InvoiceViewSet, basename="invoice")
# `payments` enregistré sur router → /payments/ (liste) + /payments/<uuid>/ (détail).
# Les paths explicites /payments/initiate/ et /payments/webhook/ sont déclarés
# AVANT router.urls pour que Django les résolve en priorité : sans ça, le
# router avalerait "initiate" et "webhook" comme s'ils étaient des pk.
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("payments/initiate/", PaymentInitiateView.as_view(), name="payments-initiate"),
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payments-webhook"),
    path("pricing/calculate/", PricingCalculateView.as_view(), name="pricing-calculate"),
    *router.urls,
]
