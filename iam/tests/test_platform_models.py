"""
TOUPAC IAM — Modèles plateforme : émission et garde-fous.

Ce qui protège une clé plateforme depuis USR-4 : des scopes explicites sans
super-scope, une restriction d'origine quand le partenaire peut la fournir, et
une révocation immédiate. L'expiration programmée a été retirée — elle imposait
de retransmettre le secret à chaque échéance pour un gain nul.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from iam.models import (
    PLATFORM_BOT_EMAIL,
    PLATFORM_KEY_PREFIX,
    PlatformCredential,
    User,
)
from iam.tests.platform_helpers import SERVICE, make_credential

pytestmark = pytest.mark.django_db


def test_platform_credential_issue_generates_correct_prefix():
    credential, secret = make_credential()

    assert credential.key_prefix.startswith(PLATFORM_KEY_PREFIX)
    assert secret.startswith(f"{credential.key_prefix}.")
    # Le préfixe plateforme ne doit pas pouvoir être confondu avec une clé
    # tenant : c'est ce qui permet aux deux backends de se départager.
    assert not credential.key_prefix.startswith("tpc_platform_platform")
    assert len(credential.key_prefix) <= 24


def test_platform_credential_secret_is_hashed_not_stored():
    credential, secret = make_credential()

    assert secret not in credential.key_hash
    assert secret.split(".", 1)[1] not in credential.key_hash
    assert credential.key_hash.startswith("pbkdf2_")


def test_platform_credential_has_no_expiry_by_default():
    """
    Sans date fournie, la clé n'expire pas.

    Une rotation programmée obligerait à retransmettre le secret au partenaire à
    chaque échéance : autant d'occasions de le voir fuiter, pour un gain nul —
    ce qui protège est la révocation immédiate, pas le calendrier.
    """
    credential, _ = PlatformCredential.issue(
        name="Sans échéance explicite", platform_service=SERVICE,
        platform_scopes=["platform:global:read"], allowed_ips=["10.0.0.0/8"],
    )

    assert credential.expires_at is None
    assert credential.days_until_expiry is None
    assert credential.is_usable()
    assert not credential.is_expired()


def test_platform_credential_accepts_an_explicit_expiry():
    """Programmer une échéance reste possible pour qui en a besoin."""
    credential, _ = make_credential(expires_at=timezone.now() + timedelta(days=30))

    assert 29 <= credential.days_until_expiry <= 30


def test_platform_credential_rejects_expires_at_too_soon():
    with pytest.raises(ValidationError) as excinfo:
        make_credential(expires_at=timezone.now() + timedelta(hours=2))

    assert "expires_at" in excinfo.value.message_dict


def test_platform_credential_rejects_unknown_platform_service():
    with pytest.raises(ValidationError) as excinfo:
        make_credential(service="foobar")

    assert "platform_service" in excinfo.value.message_dict


def test_platform_credential_rejects_unknown_scope():
    with pytest.raises(ValidationError) as excinfo:
        make_credential(scopes=["platform:voyage:destroy"])

    assert "platform_scopes" in excinfo.value.message_dict


def test_platform_credential_rejects_a_super_scope():
    """`platform:*` n'existe pas et ne doit pas pouvoir être émis."""
    with pytest.raises(ValidationError) as excinfo:
        make_credential(scopes=["platform:*"])

    assert "platform_scopes" in excinfo.value.message_dict


def test_platform_credential_accepts_the_write_scopes():
    """USR-4 ouvre l'écriture métier : réserver, expédier, payer pour un client."""
    credential, _ = make_credential(
        scopes=["platform:voyage:write", "platform:colis:write", "platform:billing:write"],
    )

    assert credential.has_platform_scope("platform:voyage:write")


def test_platform_credential_rejects_invalid_cidr():
    with pytest.raises(ValidationError) as excinfo:
        make_credential(allowed_ips=["pas-un-cidr"])

    assert "allowed_ips" in excinfo.value.message_dict


def test_platform_credential_has_no_super_scope():
    """Doctrine : pas d'équivalent d'`admin:*` côté plateforme."""
    credential, _ = make_credential(scopes=["platform:voyage:read"])

    assert credential.has_platform_scope("platform:voyage:read")
    assert not credential.has_platform_scope("platform:colis:read")
    assert not credential.has_platform_scope("platform:*")


def test_allows_ip_matches_cidr_range():
    credential, _ = make_credential(allowed_ips=["10.0.0.0/24", "52.34.10.5/32"])

    assert credential.allows_ip("10.0.0.7")
    assert credential.allows_ip("52.34.10.5")
    assert not credential.allows_ip("10.0.1.7")
    assert not credential.allows_ip("8.8.8.8")


def test_empty_allowlist_accepts_every_origin():
    """
    Vide signifie « pas de filtrage d'origine », pas « refuser tout ».

    Un service partenaire sans serveur ou multi-région n'a pas d'adresse de
    sortie stable à déclarer ; lui refuser l'accès reviendrait à lui fermer la
    plateforme.
    """
    credential, _ = make_credential(allowed_ips=[])

    assert credential.allows_ip("8.8.8.8")
    assert credential.allows_ip("10.0.0.7")


def test_is_usable_covers_expiry_and_revocation():
    credential, _ = make_credential(expires_at=timezone.now() + timedelta(days=30))
    assert credential.is_usable()

    credential.is_active = False
    assert not credential.is_usable()

    credential.is_active = True
    credential.expires_at = timezone.now() - timedelta(seconds=1)
    assert credential.is_expired()
    assert not credential.is_usable()


def test_a_key_without_expiry_is_never_expired():
    credential, _ = make_credential()

    assert credential.expires_at is None
    assert not credential.is_expired()
    assert credential.is_usable()


def test_platform_bot_user_created_by_migration():
    """La migration 0007 a tourné pour créer la base de test : le compte existe."""
    bot = User.objects.get(email=PLATFORM_BOT_EMAIL)

    assert bot.tenant is None
    assert bot.role == User.Role.SERVICE_ACCOUNT
    assert bot.has_usable_password() is False
    assert bot.is_staff is False
    assert bot.is_superuser is False


def test_platform_bot_is_recreated_if_deleted():
    """Auto-guérison : supprimer le bot ne bloque pas l'authentification suivante."""
    User.objects.filter(email=PLATFORM_BOT_EMAIL).delete()

    bot = User.get_or_create_platform_bot()

    assert bot.pk is not None
    assert bot.email == PLATFORM_BOT_EMAIL
    assert bot.tenant is None


def test_platform_bot_is_idempotent():
    first = User.get_or_create_platform_bot()
    second = User.get_or_create_platform_bot()

    assert first.pk == second.pk
