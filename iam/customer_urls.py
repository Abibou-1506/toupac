"""TOUPAC IAM — Routes du client TOUPAC (montées sur /api/v1/customer/)."""
from django.urls import path

from .customer_views import (
    CustomerCompaniesListView,
    CustomerMeView,
    MyOrdersView,
    MyPaymentsView,
    MyReservationsView,
)

urlpatterns = [
    path("me/", CustomerMeView.as_view(), name="customer-me"),
    path("companies/", CustomerCompaniesListView.as_view(), name="customer-companies"),
    path("my-reservations/", MyReservationsView.as_view(), name="customer-my-reservations"),
    path("my-orders/", MyOrdersView.as_view(), name="customer-my-orders"),
    path("my-payments/", MyPaymentsView.as_view(), name="customer-my-payments"),
]
