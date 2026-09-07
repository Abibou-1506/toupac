"""TOUPAC IAM — Routes du client TOUPAC (montées sur /api/v1/customer/)."""
from django.urls import path

from .customer_views import CustomerCompaniesListView, CustomerMeView

urlpatterns = [
    path("me/", CustomerMeView.as_view(), name="customer-me"),
    path("companies/", CustomerCompaniesListView.as_view(), name="customer-companies"),
]
