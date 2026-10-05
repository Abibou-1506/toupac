"""Tests OrderViewSet create — internal_id auto + recipient fields.

Débloque les Sheets V1.1 du backoffice toupac-web : la création de
commande via POST sans internal_id doit désormais générer un
identifiant au format CMD-{PREFIX}-{YYYYMMDD}-{NN}, et persister
recipient_name / recipient_phone (bug ancien).
"""
from datetime import date

import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Décor ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Order", slug="order-tenant")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin.order@toupac.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(admin_user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def make_place(tenant):
    counter = {"n": 0}

    def _make(name=None):
        counter["n"] += 1
        return Place.objects.create(
            tenant=tenant,
            name=name or f"Place #{counter['n']}",
            type=Place.PlaceType.STATION,
            location=Point(-17.0 + counter["n"] * 0.01, 14.0, srid=4326),
        )

    return _make


# ─── Tests ───

class TestOrderCreate:
    URL = "/api/v1/colis/orders/"

    def _base_payload(self, pickup, dropoff, **overrides):
        payload = {
            "customer_name": "Fatou Mbaye",
            "customer_phone": "+221771234567",
            "pickup_place": str(pickup.id),
            "dropoff_place": str(dropoff.id),
            "priority": "standard",
        }
        payload.update(overrides)
        return payload

    def test_create_with_auto_internal_id(self, admin_client, make_place):
        """Un POST sans internal_id le génère au format CMD-{PREFIX}-{DATE}-{NN}."""
        pickup = make_place()
        dropoff = make_place()
        response = admin_client.post(
            self.URL,
            self._base_payload(pickup, dropoff),
            format="json",
        )
        assert response.status_code == 201, response.data
        internal_id = response.data["internal_id"]
        today_str = date.today().strftime("%Y%m%d")
        assert internal_id.startswith("CMD-")
        assert today_str in internal_id
        # Format : CMD-{PREFIX}-{DATE}-{NN}
        parts = internal_id.split("-")
        assert len(parts) == 4
        assert parts[-1].isdigit()

    def test_create_with_explicit_internal_id(self, admin_client, make_place):
        """Si internal_id fourni explicitement (apps RN mobiles), il est respecté."""
        pickup = make_place()
        dropoff = make_place()
        response = admin_client.post(
            self.URL,
            self._base_payload(pickup, dropoff, internal_id="CMD-CUSTOM-001"),
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["internal_id"] == "CMD-CUSTOM-001"

    def test_create_persists_recipient_fields(self, admin_client, make_place):
        """Les champs recipient_name/phone sont persistés (bug corrigé 6 oct 2026)."""
        pickup = make_place()
        dropoff = make_place()
        response = admin_client.post(
            self.URL,
            self._base_payload(
                pickup, dropoff,
                recipient_name="Khadija Diallo",
                recipient_phone="+221771111111",
            ),
            format="json",
        )
        assert response.status_code == 201, response.data
        order_id = response.data["id"]
        # Détail : expose recipient_name/recipient_phone via OrderListSerializer
        # (dont OrderDetailSerializer hérite les fields).
        detail = admin_client.get(f"{self.URL}{order_id}/")
        assert detail.status_code == 200
        assert detail.data["recipient_name"] == "Khadija Diallo"
        assert detail.data["recipient_phone"] == "+221771111111"

    def test_sequential_internal_ids_same_day(self, admin_client, make_place):
        """Deux POST séquentiels même jour → index incrémenté sur le même préfixe."""
        pickup = make_place()
        dropoff = make_place()
        payload = self._base_payload(pickup, dropoff)
        r1 = admin_client.post(self.URL, payload, format="json")
        r2 = admin_client.post(self.URL, payload, format="json")
        assert r1.status_code == 201, r1.data
        assert r2.status_code == 201, r2.data
        id1 = r1.data["internal_id"]
        id2 = r2.data["internal_id"]
        assert id1 != id2
        # Mêmes 3 premiers segments (CMD-{PREFIX}-{DATE}), seul l'index change.
        assert id1.rsplit("-", 1)[0] == id2.rsplit("-", 1)[0]
        idx1 = int(id1.rsplit("-", 1)[1])
        idx2 = int(id2.rsplit("-", 1)[1])
        assert idx2 == idx1 + 1
