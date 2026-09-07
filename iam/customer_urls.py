"""TOUPAC IAM — Routes du client TOUPAC (montées sur /api/v1/customer/)."""
from django.urls import path

from .customer_notifications_views import (
    MyNotificationAckView,
    MyNotificationMarkReadView,
    MyNotificationsListView,
    MyNotificationsMarkAllReadView,
    MyNotificationsUnreadCountView,
)
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
    # Centre d'alertes. Les chemins littéraux passent avant `<uuid:pk>` : le
    # convertisseur `uuid` ne reconnaîtrait pas « unread-count », mais l'ordre
    # reste la garantie explicite plutôt qu'une propriété du convertisseur.
    path(
        "notifications/", MyNotificationsListView.as_view(),
        name="customer-notifications-list",
    ),
    path(
        "notifications/unread-count/", MyNotificationsUnreadCountView.as_view(),
        name="customer-notifications-unread-count",
    ),
    path(
        "notifications/mark-all-read/", MyNotificationsMarkAllReadView.as_view(),
        name="customer-notifications-mark-all-read",
    ),
    path(
        "notifications/<uuid:pk>/read/", MyNotificationMarkReadView.as_view(),
        name="customer-notification-read",
    ),
    path(
        "notifications/<uuid:pk>/ack/", MyNotificationAckView.as_view(),
        name="customer-notification-ack",
    ),
]
