"""
TOUPAC Voyage — QR de billets en RS256.

Cutover strict (pas de mode hybride) : les JWT HS256 émis avant la bascule
RS256 doivent redevenir invérifiables, au même titre qu'un token forgé.
"""
import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Passenger, Reservation, Route, Trip
from voyage.services import qr_jwt

pytestmark = pytest.mark.django_db

QR_PUBLIC_KEY_URL = "/api/v1/voyage/qr-public-key/"


# ─── Isolation de l'état module-level de qr_jwt ───
# La keypair éphémère est un cache par process (cf. qr_jwt._get_ephemeral_keypair) :
# sans reset, un test qui la déclenche polluerait tous les tests suivants du
# même run, y compris ceux qui testent explicitement l'ABSENCE de clé.

@pytest.fixture(autouse=True)
def _reset_ephemeral_keypair_cache():
    qr_jwt._ephemeral_private_pem = None
    qr_jwt._ephemeral_public_pem = None
    yield
    qr_jwt._ephemeral_private_pem = None
    qr_jwt._ephemeral_public_pem = None


def generate_test_keypair():
    """Keypair RS256 générée en mémoire pour un test — jamais committée."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


# ─── Fabriques ───

def make_tenant(slug="acme-qr"):
    return Tenant.objects.create(name=f"Transport {slug}", slug=slug)


def make_user(tenant, email="agent@acme.sn"):
    """Utilisateur rattaché au tenant, pour exercer un endpoint tenant-scopé.

    Rôle AGENT et non CLIENT : depuis USR-1, un client TOUPAC est global et ne
    peut pas porter de compagnie. Ce que le test demande à ce compte, c'est
    d'appartenir au tenant du voyage — n'importe quel rôle opérationnel fait
    l'affaire.
    """
    return User.objects.create_user(
        email=email, password="x", first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.AGENT,
    )


def make_trip(tenant, code="DKR-BKO", scheduled_at=None):
    origin = Place.objects.create(
        tenant=tenant, name="Dakar", type=Place.PlaceType.STATION,
        location=Point(-17.4441, 14.6937, srid=4326),
    )
    destination = Place.objects.create(
        tenant=tenant, name="Bamako", type=Place.PlaceType.STATION,
        location=Point(-8.0029, 12.6392, srid=4326),
    )
    route = Route.objects.create(
        tenant=tenant, name="Dakar → Bamako", code=code,
        origin_place=origin, destination_place=destination,
    )
    scheduled_at = scheduled_at or timezone.now()
    return Trip.objects.create(
        tenant=tenant, route=route, internal_id=f"VYG-{code}-{uuid.uuid4().hex[:6]}",
        departure_date=scheduled_at.date(), scheduled_at=scheduled_at,
        total_seats=45,
    )


def make_reservation(tenant, trip, seat_label="A1", amount_xof=15000):
    passenger = Passenger.objects.create(
        tenant=tenant, first_name="Moussa", last_name="Sarr", phone="+221771234567",
    )
    return Reservation.objects.create(
        tenant=tenant, trip=trip, passenger=passenger,
        seat_label=seat_label, amount_xof=amount_xof,
    )


def access_token_for(user):
    return str(ToupacTokenObtainSerializer.get_token(user).access_token)


def authenticated_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token_for(user)}")
    return client


# ─── 1-4 : sign_ticket_jwt / verify_ticket_jwt ───

def test_sign_and_verify_roundtrip_with_generated_keypair():
    private_pem, public_pem = generate_test_keypair()
    tenant = make_tenant()
    trip = make_trip(tenant)
    reservation = make_reservation(tenant, trip)

    with override_settings(
        TOUPAC_QR_PRIVATE_KEY_PEM=private_pem, TOUPAC_QR_PUBLIC_KEY_PEM=public_pem,
    ):
        token = qr_jwt.sign_ticket_jwt(reservation)
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"

        payload = qr_jwt.verify_ticket_jwt(token)

    assert payload is not None
    assert payload["sub"] == str(reservation.id)
    assert payload["trip"] == str(trip.id)
    assert payload["seat"] == "A1"
    assert payload["pax"] == "Moussa Sarr"
    assert payload["tenant"] == str(tenant.id)


def test_verify_returns_none_for_expired_token():
    private_pem, public_pem = generate_test_keypair()
    tenant = make_tenant()
    # scheduled_at + 24h dans le passé ⇒ exp expiré dès la signature.
    trip = make_trip(tenant, scheduled_at=timezone.now() - timedelta(days=3))
    reservation = make_reservation(tenant, trip)

    with override_settings(
        TOUPAC_QR_PRIVATE_KEY_PEM=private_pem, TOUPAC_QR_PUBLIC_KEY_PEM=public_pem,
    ):
        token = qr_jwt.sign_ticket_jwt(reservation)
        payload = qr_jwt.verify_ticket_jwt(token)

    assert payload is None


def test_verify_returns_none_for_tampered_token():
    private_pem, public_pem = generate_test_keypair()
    tenant = make_tenant()
    trip = make_trip(tenant)
    reservation = make_reservation(tenant, trip)

    with override_settings(
        TOUPAC_QR_PRIVATE_KEY_PEM=private_pem, TOUPAC_QR_PUBLIC_KEY_PEM=public_pem,
    ):
        token = qr_jwt.sign_ticket_jwt(reservation)
        header, payload_segment, signature = token.split(".")
        # Bascule un caractère au milieu du payload — la signature ne colle plus.
        mid = len(payload_segment) // 2
        flipped_char = "A" if payload_segment[mid] != "A" else "B"
        tampered_payload = payload_segment[:mid] + flipped_char + payload_segment[mid + 1:]
        tampered_token = f"{header}.{tampered_payload}.{signature}"

        result = qr_jwt.verify_ticket_jwt(tampered_token)

    assert result is None


def test_verify_returns_none_for_hs256_legacy_token():
    private_pem, public_pem = generate_test_keypair()
    legacy_payload = {
        "sub": str(uuid.uuid4()), "seat": "A1",
        "iat": int(timezone.now().timestamp()),
        "exp": int((timezone.now() + timedelta(hours=1)).timestamp()),
    }
    legacy_token = jwt.encode(legacy_payload, "some-arbitrary-hs256-secret", algorithm="HS256")

    with override_settings(
        TOUPAC_QR_PRIVATE_KEY_PEM=private_pem, TOUPAC_QR_PUBLIC_KEY_PEM=public_pem,
    ):
        result = qr_jwt.verify_ticket_jwt(legacy_token)

    assert result is None


# ─── 5-6 : endpoint public GET /voyage/qr-public-key/ ───

def test_public_key_endpoint_returns_pem_when_configured():
    _, public_pem = generate_test_keypair()

    with override_settings(TOUPAC_QR_PUBLIC_KEY_PEM=public_pem):
        response = APIClient().get(QR_PUBLIC_KEY_URL)

    assert response.status_code == 200, response.data
    assert response.data["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    assert response.data["public_key_pem"].strip().endswith("-----END PUBLIC KEY-----")


def test_public_key_endpoint_returns_503_when_no_key(tmp_path):
    unreachable_path = tmp_path / "no_such_key.pem"
    with (
        override_settings(TOUPAC_QR_PRIVATE_KEY_PEM="", TOUPAC_QR_PUBLIC_KEY_PEM=""),
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(qr_jwt, "_COMMITTED_PUBLIC_KEY_PATH", unreachable_path)
        response = APIClient().get(QR_PUBLIC_KEY_URL)

    assert response.status_code == 503, response.data
    assert response.data["detail"] == "QR key not configured"


def test_public_key_endpoint_requires_no_authentication():
    """L'endpoint est public par nature : pas de 401 même sans token."""
    _, public_pem = generate_test_keypair()
    with override_settings(TOUPAC_QR_PUBLIC_KEY_PEM=public_pem):
        response = APIClient().get(QR_PUBLIC_KEY_URL)
    assert response.status_code != 401


# ─── 7 : le manifest expose qr_public_key ───

def test_manifest_exposes_public_key():
    _, public_pem = generate_test_keypair()
    tenant = make_tenant()
    user = make_user(tenant)
    trip = make_trip(tenant)

    with override_settings(TOUPAC_QR_PUBLIC_KEY_PEM=public_pem):
        client = authenticated_client(user)
        response = client.get(f"/api/v1/voyage/trips/{trip.id}/manifest/")

    assert response.status_code == 200, response.data
    assert response.data["qr_public_key"] is not None
    assert response.data["qr_public_key"].startswith("-----BEGIN PUBLIC KEY-----")
