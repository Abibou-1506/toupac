"""
TOUPAC IAM — Connexion des clients par code à usage unique.

Le parcours entier passe par de vraies requêtes HTTP : ce qui compte est le
contrat vu par l'application cliente (codes de statut, forme des réponses,
claims du jeton), et il dépend d'interactions — middleware, throttling,
notifications — qu'un appel direct aux helpers court-circuiterait.

Le code envoyé est relu depuis le `NotificationLog` plutôt que capturé par un
mock : cela vérifie au passage que le gabarit existe, qu'il se rend avec les
variables du catalogue, et que l'envoi sans compagnie ne casse pas.
"""
import re

import jwt
import pytest

from iam.models import User
from iam.otp import OTP_MAX_ATTEMPTS, peek_challenge
from notifications.models import NotificationLog

pytestmark = pytest.mark.django_db

REQUEST_URL = "/api/v1/auth/otp/request/"
VERIFY_URL = "/api/v1/auth/otp/verify/"


@pytest.fixture(autouse=True)
def _otp_templates():
    """Les gabarits système sont une donnée de production, pas une fixture de test."""
    from io import StringIO

    from django.core.management import call_command

    call_command("seed_notification_templates", stdout=StringIO())


def request_code(api_client, **payload):
    return api_client.post(REQUEST_URL, payload, format="json")


def sent_code(recipient):
    """Récupère le code réellement délivré, depuis le journal d'envoi."""
    log = NotificationLog.objects.filter(recipient=recipient).order_by("-created_at").first()
    assert log is not None, f"aucune notification envoyée à {recipient}"
    match = re.search(r"\b(\d{6})\b", log.content)
    assert match, f"aucun code à six chiffres dans : {log.content!r}"
    return match.group(1)


# ─── Masquage de la cible ───

@pytest.mark.parametrize(("target_type", "target", "expected"), [
    ("email", "fatou@example.sn", "fa***@example.sn"),
    ("email", "ab@ex.com", "**@ex.com"),
    ("email", "a@b", "*@b"),                 # partie locale trop courte pour un indice
    ("email", "pas-un-email", "************"),  # pas d'arobase : on ne devine pas
    ("email", "", ""),
    ("phone", "+221771234567", "+2217****67"),
    ("phone", "1234567", "*******"),         # trop court pour masquer utilement
    ("phone", "+7712", "*****"),
    ("phone", "", ""),
    ("inconnu", "xyz", "***"),               # type imprévu : on masque tout
])
def test_mask_target_never_leaks_and_never_raises(target_type, target, expected):
    """
    Une cible trop courte est entièrement masquée, jamais rendue en clair.

    Le masque sert à confirmer « c'est bien mon adresse » sans la divulguer à
    qui n'aurait fait que deviner un identifiant. Retourner la valeur telle
    quelle sur un cas limite annulerait cette protection.
    """
    from iam.otp import mask_target

    assert mask_target(target_type, target) == expected


# ─── Demande de code ───

def test_request_by_email_creates_challenge(api_client):
    response = request_code(api_client, email="fatou@example.sn")

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "email"
    assert body["target_masked"] == "fa***@example.sn"
    assert body["expires_in_seconds"] == 300
    assert peek_challenge(body["challenge_id"]) is not None


def test_request_by_phone_creates_challenge(api_client):
    response = request_code(api_client, phone="+221771234567")

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "sms"
    assert body["target_masked"] == "+2217****67"
    assert peek_challenge(body["challenge_id"]) is not None


def test_request_creates_new_client_if_unknown(api_client):
    assert not User.objects.filter(email="inconnu@example.sn").exists()

    request_code(api_client, email="inconnu@example.sn")

    user = User.objects.get(email="inconnu@example.sn")
    assert user.role == User.Role.CLIENT
    assert user.tenant is None
    assert user.has_usable_password() is False


def test_request_reuses_existing_client(api_client, client_fatou):
    before = User.objects.filter(role=User.Role.CLIENT).count()

    response = request_code(api_client, email=client_fatou.email)

    assert response.status_code == 200
    assert User.objects.filter(role=User.Role.CLIENT).count() == before
    assert peek_challenge(response.json()["challenge_id"])["user_id"] == str(client_fatou.id)


def test_request_normalises_email_case(api_client):
    request_code(api_client, email="Fatou@Example.SN")

    assert User.objects.filter(email="fatou@example.sn").exists()


def test_request_without_contact_returns_400(api_client):
    assert request_code(api_client).status_code == 400
    assert request_code(api_client, email="", phone="").status_code == 400


def test_request_refuses_an_email_belonging_to_staff(api_client, user_admin_a):
    """Un compte d'exploitation ne se laisse pas détourner en compte client."""
    response = request_code(api_client, email=user_admin_a.email)

    assert response.status_code == 400
    user_admin_a.refresh_from_db()
    assert user_admin_a.role == User.Role.ADMIN


def test_request_sends_the_notification_without_tenant(api_client):
    """L'envoi ne porte aucune compagnie : le client est global."""
    request_code(api_client, phone="+221771234567")

    log = NotificationLog.objects.get(recipient="+221771234567")
    assert log.tenant is None
    assert log.event_code == "notif.auth.otp_signin.v1"
    assert log.status == NotificationLog.Status.SENT


def test_request_succeeds_even_when_delivery_fails(api_client, monkeypatch):
    """
    Un provider en panne ne doit pas révéler l'échec à l'appelant.

    Le challenge existe déjà ; renvoyer une erreur renseignerait sur l'existence
    du compte et empêcherait une nouvelle tentative.
    """
    from notifications.services import NotificationService

    def boom(*args, **kwargs):
        raise RuntimeError("provider indisponible")

    monkeypatch.setattr(NotificationService, "send_notification", boom)

    response = request_code(api_client, email="fatou@example.sn")

    assert response.status_code == 200
    assert peek_challenge(response.json()["challenge_id"]) is not None


def test_otp_code_stored_as_hash_not_plaintext(api_client):
    response = request_code(api_client, phone="+221771234567")
    code = sent_code("+221771234567")

    payload = peek_challenge(response.json()["challenge_id"])

    assert code not in str(payload)
    assert payload["code_hash"] != code
    assert len(payload["code_hash"]) == 64  # SHA-256 en hexadécimal


# ─── Vérification ───

def test_verify_correct_code_returns_jwt(api_client):
    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]
    code = sent_code("+221771234567")

    response = api_client.post(
        VERIFY_URL, {"challenge_id": challenge_id, "code": code}, format="json",
    )

    assert response.status_code == 200
    body = response.json()
    claims = jwt.decode(body["access"], options={"verify_signature": False})
    assert claims["role"] == User.Role.CLIENT
    assert claims["tenant_id"] is None
    assert body["refresh"]


def test_verify_consumes_the_challenge(api_client):
    """Un code valide ne sert qu'une fois — rejouer la requête échoue."""
    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]
    code = sent_code("+221771234567")
    payload = {"challenge_id": challenge_id, "code": code}

    assert api_client.post(VERIFY_URL, payload, format="json").status_code == 200

    replay = api_client.post(VERIFY_URL, payload, format="json")
    assert replay.status_code == 401
    assert replay.json()["code"] == "not_found"


def test_verify_wrong_code_increments_attempts(api_client):
    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]

    response = api_client.post(
        VERIFY_URL, {"challenge_id": challenge_id, "code": "000000"}, format="json",
    )

    assert response.status_code == 401
    assert response.json()["code"] == "wrong_code"
    assert peek_challenge(challenge_id)["attempts"] == 1


def test_verify_max_attempts_deletes_challenge(api_client):
    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]
    code = sent_code("+221771234567")

    for _ in range(OTP_MAX_ATTEMPTS):
        api_client.post(
            VERIFY_URL, {"challenge_id": challenge_id, "code": "000000"}, format="json",
        )

    assert peek_challenge(challenge_id) is None
    # Même le bon code ne sert plus : il faut redemander.
    final = api_client.post(
        VERIFY_URL, {"challenge_id": challenge_id, "code": code}, format="json",
    )
    assert final.status_code == 401
    assert final.json()["code"] == "not_found"


def test_verify_unknown_challenge_returns_401(api_client):
    response = api_client.post(
        VERIFY_URL,
        {"challenge_id": "11111111-2222-3333-4444-555555555555", "code": "123456"},
        format="json",
    )

    assert response.status_code == 401
    assert response.json()["code"] == "not_found"


def test_verify_rejects_a_deactivated_account(api_client, client_fatou):
    challenge_id = request_code(api_client, email=client_fatou.email).json()["challenge_id"]
    code = sent_code(client_fatou.email)
    User.objects.filter(pk=client_fatou.pk).update(is_active=False)

    response = api_client.post(
        VERIFY_URL, {"challenge_id": challenge_id, "code": code}, format="json",
    )

    assert response.status_code == 401


def test_expired_challenge_is_refused(api_client):
    """L'échéance stockée fait foi, sans dépendre de la purge du cache."""
    from datetime import timedelta

    from django.core.cache import cache
    from django.utils import timezone

    from iam.otp import _challenge_key

    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]
    code = sent_code("+221771234567")

    key = _challenge_key(challenge_id)
    payload = cache.get(key)
    payload["expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
    cache.set(key, payload, timeout=300)

    response = api_client.post(
        VERIFY_URL, {"challenge_id": challenge_id, "code": code}, format="json",
    )

    assert response.status_code == 401
    assert response.json()["code"] == "expired"
    assert peek_challenge(challenge_id) is None


def test_failed_attempt_does_not_extend_the_window(api_client):
    """
    Réécrire le challenge après un échec conserve l'échéance d'origine.

    Sans cela, une tentative fausse toutes les quatre minutes prolongerait le
    code indéfiniment.
    """
    challenge_id = request_code(api_client, phone="+221771234567").json()["challenge_id"]
    before = peek_challenge(challenge_id)["expires_at"]

    api_client.post(VERIFY_URL, {"challenge_id": challenge_id, "code": "000000"}, format="json")

    assert peek_challenge(challenge_id)["expires_at"] == before
