"""TOUPAC Notifications — Modèle Notification, item du centre d'alertes (Ticket A)."""
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _make(tenant, user, **overrides):
    payload = {
        "tenant": tenant,
        "event_code": "notif.payment.confirmed.v1",
        "recipient_user": user,
        "trigger_scope": Notification.TriggerScope.USER,
        "priority": Notification.Priority.CRITICAL,
        "title": "Paiement confirmé",
        "body": "Votre paiement a été confirmé.",
    }
    return Notification.objects.create(**{**payload, **overrides})


def test_notification_created_with_user_recipient(tenant_a, user_admin_a):
    notification = _make(tenant_a, user_admin_a)

    assert notification.recipient_user == user_admin_a
    assert notification.trigger_scope == "user"
    assert notification.read_at is None
    assert notification.acked_at is None
    assert notification.trigger_role == ""
    assert notification.idempotency_key == ""


def test_notification_role_broadcast_records_target_role(tenant_a, user_dispatcher_a):
    """trigger_role trace l'origine du broadcast, il ne rejoue pas la résolution."""
    from iam.models import User

    notification = _make(
        tenant_a, user_dispatcher_a,
        event_code="notif.dispatch.conflict.v1",
        trigger_scope=Notification.TriggerScope.ROLE,
        trigger_role=User.Role.DISPATCHER,
    )

    assert notification.trigger_scope == "role"
    assert notification.trigger_role == "dispatcher"


def test_notification_unique_idempotency_key_per_tenant_user(tenant_a, user_admin_a):
    _make(tenant_a, user_admin_a, idempotency_key="pay-001")

    with pytest.raises(IntegrityError), transaction.atomic():
        _make(tenant_a, user_admin_a, idempotency_key="pay-001")


def test_notification_blank_idempotency_key_is_not_constrained(tenant_a, user_admin_a):
    """Contrainte partielle : sans clé, deux notifications légitimes coexistent."""
    _make(tenant_a, user_admin_a)
    _make(tenant_a, user_admin_a)

    assert Notification.objects.filter(recipient_user=user_admin_a).count() == 2


def test_notification_same_idempotency_key_allowed_for_another_user(
    tenant_a, user_admin_a, user_dispatcher_a,
):
    """L'idempotence est par destinataire : un broadcast partage sa clé entre N users."""
    _make(tenant_a, user_admin_a, idempotency_key="broadcast-001")
    _make(tenant_a, user_dispatcher_a, idempotency_key="broadcast-001")

    assert Notification.objects.filter(idempotency_key="broadcast-001").count() == 2


def test_notification_tenant_isolation(tenant_a, tenant_b, user_admin_a, user_admin_b):
    _make(tenant_a, user_admin_a)
    _make(tenant_b, user_admin_b)

    scoped = Notification.objects.for_tenant(tenant_a)

    assert [n.recipient_user for n in scoped] == [user_admin_a]


def test_notification_read_and_ack_are_independent(tenant_a, user_admin_a):
    notification = _make(tenant_a, user_admin_a, event_code="notif.dispatch.assigned.v1")

    notification.read_at = timezone.now()
    notification.save(update_fields=["read_at"])
    notification.refresh_from_db()
    assert notification.read_at is not None
    assert notification.acked_at is None

    notification.acked_at = timezone.now()
    notification.save(update_fields=["acked_at"])
    notification.refresh_from_db()
    assert notification.read_at is not None
    assert notification.acked_at is not None


def test_notification_log_can_point_to_a_notification(tenant_a, user_admin_a):
    """Une tentative d'envoi se rattache à l'item de centre d'alertes qu'elle sert."""
    from notifications.models import NotificationLog

    notification = _make(tenant_a, user_admin_a)
    log = NotificationLog.objects.create(
        tenant=tenant_a, notification=notification, channel="push",
        recipient="device-token", event_code=notification.event_code,
    )

    assert list(notification.delivery_attempts.all()) == [log]


def test_notification_log_stays_valid_without_a_notification(tenant_a):
    """Un OTP SMS n'a pas de contrepartie in-app : la FK reste nulle."""
    from notifications.models import NotificationLog

    log = NotificationLog.objects.create(
        tenant=tenant_a, channel="sms", recipient="+221770000000",
        event_code="notif.auth.otp_signin.v1",
    )

    assert log.notification is None
