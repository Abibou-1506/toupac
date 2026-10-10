"""TOUPAC Fleet — Tests Phase 3 Vague 2.

Couvre :
- CRUD ``DriverHRNote`` + blocage DELETE pour non-superadmin (audit).
- CRUD ``DriverDocument`` + exposition ``file_url`` absolue.
- Upload photo chauffeur multipart.
- Actions ``suspend`` / ``reactivate`` + création automatique de HRNote.
- Endpoint ``stats`` (trips_this_month/year/last_month, average_rating null,
  ponctuality_pct null — dette V1.1 documentée).
- ``recent_hr_notes`` top-5 + ``assigned_vehicles`` (reverse FK Phase 2).
"""
import io

import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from fleet.models import (
    Driver,
    DriverDocument,
    DriverHRNote,
    Vehicle,
    VehicleType,
)
from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import Route, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Fixtures ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Phase3 Transport", slug="phase3-fleet")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Phase3 Bis", slug="phase3-fleet-bis")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin@phase3-fleet.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def other_admin_user(other_tenant):
    return User.objects.create_user(
        email="admin@phase3-fleet-bis.sn", password=PASSWORD,
        first_name="Omar", last_name="Fall",
        tenant=other_tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def superadmin_user(tenant):
    return User.objects.create_user(
        email="root@phase3-fleet.sn", password=PASSWORD,
        first_name="Root", last_name="User",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True, is_superuser=True,
    )


def _client_for(user):
    client = APIClient()
    token = str(ToupacTokenObtainSerializer.get_token(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def admin_client(admin_user):
    return _client_for(admin_user)


@pytest.fixture
def other_admin_client(other_admin_user):
    return _client_for(other_admin_user)


@pytest.fixture
def superadmin_client(superadmin_user):
    return _client_for(superadmin_user)


@pytest.fixture
def driver_user(tenant):
    return User.objects.create_user(
        email="moussa@phase3-fleet.sn", password=PASSWORD,
        first_name="Moussa", last_name="Diallo",
        tenant=tenant, role=User.Role.DRIVER,
    )


@pytest.fixture
def driver(tenant, driver_user):
    return Driver.objects.create(
        tenant=tenant, user=driver_user,
        matricule="TPC-CH-00077",
        license_number="SN-DL-00077", license_class="D",
    )


@pytest.fixture
def other_driver(other_tenant):
    du = User.objects.create_user(
        email="bass@phase3-fleet-bis.sn", password=PASSWORD,
        first_name="Bass", last_name="Fall",
        tenant=other_tenant, role=User.Role.DRIVER,
    )
    return Driver.objects.create(
        tenant=other_tenant, user=du,
        license_number="SN-DL-99999",
    )


def _tiny_png_bytes() -> bytes:
    img = Image.new("RGB", (1, 1), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── DriverHRNote ───

class TestDriverHRNote:
    def test_driver_hr_note_crud(self, admin_client, driver):
        resp = admin_client.post(
            "/api/v1/fleet/driver-hr-notes/",
            {"driver": str(driver.id), "text": "Formation sécurité OK.",
             "kind": "training"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        nid = resp.data["id"]
        assert resp.data["kind"] == "training"
        assert resp.data["by_name"]  # auteur rempli automatiquement

        resp = admin_client.get("/api/v1/fleet/driver-hr-notes/")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        assert any(n["id"] == nid for n in data)

    def test_driver_hr_note_delete_blocked_for_non_superadmin(
        self, admin_client, tenant, driver,
    ):
        note = DriverHRNote.objects.create(
            tenant=tenant, driver=driver, text="Avertissement — retard.",
            kind=DriverHRNote.Kind.WARNING,
        )
        resp = admin_client.delete(f"/api/v1/fleet/driver-hr-notes/{note.id}/")
        assert resp.status_code == 403
        assert DriverHRNote.objects.filter(pk=note.id).exists()

    def test_driver_hr_note_delete_allowed_superadmin(
        self, superadmin_client, tenant, driver,
    ):
        note = DriverHRNote.objects.create(
            tenant=tenant, driver=driver, text="Note à supprimer.",
            kind=DriverHRNote.Kind.NOTE,
        )
        resp = superadmin_client.delete(
            f"/api/v1/fleet/driver-hr-notes/{note.id}/",
        )
        assert resp.status_code == 204
        assert not DriverHRNote.objects.filter(pk=note.id).exists()

    def test_driver_hr_note_tenant_isolation(
        self, admin_client, tenant, other_tenant, driver, other_driver,
    ):
        mine = DriverHRNote.objects.create(
            tenant=tenant, driver=driver, text="Mienne.",
        )
        theirs = DriverHRNote.objects.create(
            tenant=other_tenant, driver=other_driver, text="Pas mienne.",
        )
        resp = admin_client.get("/api/v1/fleet/driver-hr-notes/")
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {n["id"] for n in data}
        assert str(mine.id) in ids
        assert str(theirs.id) not in ids
        resp = admin_client.get(f"/api/v1/fleet/driver-hr-notes/{theirs.id}/")
        assert resp.status_code == 404


# ─── DriverDocument ───

class TestDriverDocument:
    def test_driver_document_crud(self, admin_client, driver):
        upload = SimpleUploadedFile(
            "permis.pdf", b"PDF-fake", content_type="application/pdf",
        )
        resp = admin_client.post(
            "/api/v1/fleet/driver-documents/",
            {"driver": str(driver.id), "type": "license_scan",
             "number": "SN-DL-00077", "file": upload},
            format="multipart",
        )
        assert resp.status_code == 201, resp.content
        did = resp.data["id"]

        resp = admin_client.get(f"/api/v1/fleet/driver-documents/{did}/")
        assert resp.status_code == 200
        assert resp.data["type"] == "license_scan"

    def test_driver_document_tenant_isolation(
        self, admin_client, tenant, other_tenant, driver, other_driver,
    ):
        mine = DriverDocument.objects.create(
            tenant=tenant, driver=driver, type="contract", number="C-1",
        )
        theirs = DriverDocument.objects.create(
            tenant=other_tenant, driver=other_driver, type="contract", number="C-2",
        )
        resp = admin_client.get("/api/v1/fleet/driver-documents/")
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert str(mine.id) in ids
        assert str(theirs.id) not in ids

    def test_driver_document_file_url_absolute(self, admin_client, driver):
        upload = SimpleUploadedFile(
            "p.pdf", b"PDF", content_type="application/pdf",
        )
        resp = admin_client.post(
            "/api/v1/fleet/driver-documents/",
            {"driver": str(driver.id), "type": "medical_check", "file": upload},
            format="multipart",
        )
        assert resp.status_code == 201, resp.content
        did = resp.data["id"]
        resp = admin_client.get(f"/api/v1/fleet/driver-documents/{did}/")
        url = resp.data["file_url"]
        assert url is not None
        assert url.startswith("http://") or url.startswith("https://")


# ─── Driver photo upload ───

class TestDriverPhotoUpload:
    def test_driver_photo_upload(self, admin_client, driver):
        png = _tiny_png_bytes()
        upload = SimpleUploadedFile("photo.png", png, content_type="image/png")
        resp = admin_client.post(
            f"/api/v1/fleet/drivers/{driver.id}/photo/",
            {"photo": upload}, format="multipart",
        )
        assert resp.status_code == 200, resp.content

        resp = admin_client.get(f"/api/v1/fleet/drivers/{driver.id}/")
        assert resp.status_code == 200
        url = resp.data["photo"]
        assert url is not None
        assert url.startswith("http://") or url.startswith("https://")


# ─── Suspend / Reactivate ───

class TestDriverSuspendReactivate:
    def test_driver_suspend_creates_hr_note(
        self, admin_client, admin_user, driver,
    ):
        reason = "Retards répétés et comportement inapproprié constaté le 05/10."
        resp = admin_client.post(
            f"/api/v1/fleet/drivers/{driver.id}/suspend/",
            {"reason": reason}, format="json",
        )
        assert resp.status_code == 200, resp.content
        driver.refresh_from_db()
        assert driver.status == Driver.Status.OFF_DUTY

        notes = DriverHRNote.objects.filter(driver=driver, kind="suspension")
        assert notes.count() == 1
        note = notes.first()
        assert note.text == reason
        assert note.by_id == admin_user.id

    def test_driver_suspend_requires_reason(self, admin_client, driver):
        # Pas de reason
        resp = admin_client.post(
            f"/api/v1/fleet/drivers/{driver.id}/suspend/",
            {}, format="json",
        )
        assert resp.status_code == 400

        # Reason trop court
        resp = admin_client.post(
            f"/api/v1/fleet/drivers/{driver.id}/suspend/",
            {"reason": "trop"}, format="json",
        )
        assert resp.status_code == 400

    def test_driver_reactivate_creates_hr_note(
        self, admin_client, tenant, driver,
    ):
        driver.status = Driver.Status.OFF_DUTY
        driver.save(update_fields=["status"])
        resp = admin_client.post(
            f"/api/v1/fleet/drivers/{driver.id}/reactivate/",
            {"reason": "Fin de la mesure disciplinaire."}, format="json",
        )
        assert resp.status_code == 200, resp.content
        driver.refresh_from_db()
        assert driver.status == Driver.Status.AVAILABLE
        notes = DriverHRNote.objects.filter(driver=driver, kind="reactivation")
        assert notes.count() == 1


# ─── Stats ───

class TestDriverStats:
    def test_driver_stats_endpoint(self, admin_client, tenant, driver):
        now = timezone.now()
        place_a = Place.objects.create(
            tenant=tenant, name="A", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        )
        place_b = Place.objects.create(
            tenant=tenant, name="B", type=Place.PlaceType.STATION,
            location=Point(-16.9246, 14.7886, srid=4326),
        )
        route = Route.objects.create(
            tenant=tenant, name="A→B", code="A-B",
            origin_place=place_a, destination_place=place_b,
        )
        # 2 trips ce mois-ci
        for i in range(2):
            Trip.objects.create(
                tenant=tenant, route=route, internal_id=f"VYG-STATS-{i}",
                departure_date=now.date(), scheduled_at=now,
                total_seats=20, driver=driver,
            )
        resp = admin_client.get(f"/api/v1/fleet/drivers/{driver.id}/stats/")
        assert resp.status_code == 200
        data = resp.data
        for key in (
            "trips_this_month", "trips_this_year", "trips_last_month",
            "average_rating", "ponctuality_pct",
        ):
            assert key in data
        assert data["trips_this_month"] == 2
        assert data["trips_this_year"] >= 2
        # Dette V1.1 — explicitement null
        assert data["average_rating"] is None
        assert data["ponctuality_pct"] is None


# ─── Serializer enrichments ───

class TestDriverDetailEnrich:
    def test_driver_recent_hr_notes_limit_5(
        self, admin_client, tenant, driver,
    ):
        for i in range(7):
            DriverHRNote.objects.create(
                tenant=tenant, driver=driver, text=f"Note {i}",
                kind=DriverHRNote.Kind.NOTE,
            )
        resp = admin_client.get(f"/api/v1/fleet/drivers/{driver.id}/")
        assert resp.status_code == 200
        assert len(resp.data["recent_hr_notes"]) == 5

    def test_driver_assigned_vehicles_reverse(
        self, admin_client, tenant, driver,
    ):
        vt = VehicleType.objects.create(
            tenant=tenant, name="Bus-P3", default_capacity=20,
        )
        v = Vehicle.objects.create(
            tenant=tenant, vehicle_type=vt,
            plate_number="DK-7777-P3", make="Toyota", model_name="Hiace",
            capacity=15, assigned_driver=driver,
        )
        resp = admin_client.get(f"/api/v1/fleet/drivers/{driver.id}/")
        assert resp.status_code == 200
        assigned = resp.data["assigned_vehicles"]
        assert len(assigned) == 1
        assert assigned[0]["plate_number"] == "DK-7777-P3"
        assert assigned[0]["id"] == str(v.id)
