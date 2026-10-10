"""TOUPAC Fleet — Tests Phase 2 Vague 2.

Couvre :
- CRUD ``VehicleMaintenance`` (incluant filter/ordering, isolation tenant).
- FK ``Vehicle.assigned_driver`` (SET_NULL, PATCH, exposition nested).
- ``recent_maintenances`` top-5 dans la page détail Vehicle.
- Upload photo multipart (``POST /vehicles/{id}/photo/``), validations.
- Export ZIP des documents (``GET /vehicles/{id}/documents/export/``).
"""
import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from fleet.models import (
    Driver,
    Vehicle,
    VehicleDocument,
    VehicleMaintenance,
    VehicleType,
)
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Fixtures ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Phase2 Transport", slug="phase2-fleet")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Phase2 Bis", slug="phase2-fleet-bis")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin@phase2-fleet.sn", password=PASSWORD,
        first_name="Awa", last_name="Diop",
        tenant=tenant, role=User.Role.ADMIN, is_staff=True,
    )


@pytest.fixture
def other_admin_user(other_tenant):
    return User.objects.create_user(
        email="admin@phase2-fleet-bis.sn", password=PASSWORD,
        first_name="Oumar", last_name="Sow",
        tenant=other_tenant, role=User.Role.ADMIN, is_staff=True,
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
def vehicle_type(tenant):
    return VehicleType.objects.create(
        tenant=tenant, name="Bus 50", default_capacity=50,
    )


@pytest.fixture
def vehicle(tenant, vehicle_type):
    return Vehicle.objects.create(
        tenant=tenant, vehicle_type=vehicle_type,
        plate_number="DK-9999-ZZ", make="Toyota", model_name="Coaster",
        capacity=30,
    )


@pytest.fixture
def other_vehicle(other_tenant):
    vt = VehicleType.objects.create(
        tenant=other_tenant, name="Bus 30", default_capacity=30,
    )
    return Vehicle.objects.create(
        tenant=other_tenant, vehicle_type=vt,
        plate_number="DK-0001-BB", make="Hiace", model_name="L",
        capacity=18,
    )


@pytest.fixture
def driver_user(tenant):
    return User.objects.create_user(
        email="moussa@phase2-fleet.sn", password=PASSWORD,
        first_name="Moussa", last_name="Diallo",
        tenant=tenant, role=User.Role.DRIVER,
    )


@pytest.fixture
def driver(tenant, driver_user):
    return Driver.objects.create(
        tenant=tenant, user=driver_user,
        matricule="TPC-CH-00042",
        license_number="SN-DL-00002", license_class="D",
    )


def _tiny_png_bytes() -> bytes:
    img = Image.new("RGB", (1, 1), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── VehicleMaintenance CRUD ───

class TestVehicleMaintenanceCRUD:
    def test_vehicle_maintenance_crud(self, admin_client, tenant, vehicle):
        payload = {
            "vehicle": str(vehicle.id),
            "at": "2026-06-15",
            "type": "oil_change",
            "odometer_km": 125_000,
            "shop": "Garage Dakar",
            "cost_xof": 85_000,
            "notes": "Huile 10W-40 + filtre.",
        }
        resp = admin_client.post(
            "/api/v1/fleet/vehicle-maintenances/", payload, format="json",
        )
        assert resp.status_code == 201, resp.content
        mid = resp.data["id"]
        assert resp.data["type"] == "oil_change"
        assert resp.data["odometer_km"] == 125_000

        # GET detail
        resp = admin_client.get(f"/api/v1/fleet/vehicle-maintenances/{mid}/")
        assert resp.status_code == 200
        assert resp.data["shop"] == "Garage Dakar"

        # LIST
        resp = admin_client.get("/api/v1/fleet/vehicle-maintenances/")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        assert any(m["id"] == mid for m in data)

        # PATCH
        resp = admin_client.patch(
            f"/api/v1/fleet/vehicle-maintenances/{mid}/",
            {"cost_xof": 90_000}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["cost_xof"] == 90_000

        # DELETE
        resp = admin_client.delete(
            f"/api/v1/fleet/vehicle-maintenances/{mid}/",
        )
        assert resp.status_code == 204
        assert not VehicleMaintenance.objects.filter(pk=mid).exists()

    def test_vehicle_maintenance_ordering_filter_by_vehicle(
        self, admin_client, tenant, vehicle, vehicle_type,
    ):
        other = Vehicle.objects.create(
            tenant=tenant, vehicle_type=vehicle_type,
            plate_number="DK-8888-AA", capacity=20,
        )
        for i, d in enumerate(["2026-03-01", "2026-05-01", "2026-01-01"]):
            VehicleMaintenance.objects.create(
                tenant=tenant, vehicle=vehicle, at=d,
                type="tires", odometer_km=100_000 + i * 1000,
            )
        VehicleMaintenance.objects.create(
            tenant=tenant, vehicle=other, at="2026-04-01",
            type="oil_change", odometer_km=50_000,
        )
        resp = admin_client.get(
            f"/api/v1/fleet/vehicle-maintenances/?vehicle={vehicle.id}",
        )
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        assert len(data) == 3
        dates = [m["at"] for m in data]
        assert dates == sorted(dates, reverse=True)

    def test_vehicle_maintenance_tenant_isolation(
        self, admin_client, other_admin_client, tenant, vehicle, other_vehicle,
    ):
        mine = VehicleMaintenance.objects.create(
            tenant=tenant, vehicle=vehicle, at="2026-04-10",
            type="oil_change", odometer_km=130_000,
        )
        theirs = VehicleMaintenance.objects.create(
            tenant=other_vehicle.tenant, vehicle=other_vehicle,
            at="2026-04-11", type="tires", odometer_km=60_000,
        )
        resp = admin_client.get("/api/v1/fleet/vehicle-maintenances/")
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {m["id"] for m in data}
        assert str(mine.id) in ids
        assert str(theirs.id) not in ids

        resp = admin_client.get(
            f"/api/v1/fleet/vehicle-maintenances/{theirs.id}/",
        )
        assert resp.status_code == 404


# ─── Vehicle.assigned_driver ───

class TestVehicleAssignedDriver:
    def test_vehicle_assigned_driver_fk_patch(
        self, admin_client, vehicle, driver,
    ):
        resp = admin_client.patch(
            f"/api/v1/fleet/vehicles/{vehicle.id}/",
            {"assigned_driver_id": str(driver.id)}, format="json",
        )
        assert resp.status_code == 200, resp.content

        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200
        nested = resp.data["assigned_driver"]
        assert nested is not None
        assert nested["id"] == str(driver.id)
        assert nested["matricule"] == "TPC-CH-00042"
        assert nested["full_name"].startswith("Moussa")

        # SET_NULL on driver delete
        driver_id = driver.id
        driver.delete()
        vehicle.refresh_from_db()
        assert vehicle.assigned_driver_id is None
        _ = driver_id  # unused suppressor

    def test_vehicle_recent_maintenances_limit_5(
        self, admin_client, tenant, vehicle,
    ):
        for i in range(7):
            VehicleMaintenance.objects.create(
                tenant=tenant, vehicle=vehicle,
                at=f"2026-0{(i % 9) + 1}-10",
                type="oil_change", odometer_km=100_000 + i * 500,
            )
        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200
        assert len(resp.data["recent_maintenances"]) == 5


# ─── Photo upload ───

class TestVehiclePhotoUpload:
    def test_vehicle_photo_upload_multipart(self, admin_client, vehicle):
        png = _tiny_png_bytes()
        upload = SimpleUploadedFile("photo.png", png, content_type="image/png")
        resp = admin_client.post(
            f"/api/v1/fleet/vehicles/{vehicle.id}/photo/",
            {"photo": upload}, format="multipart",
        )
        assert resp.status_code == 200, resp.content

        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200
        url = resp.data["photo"]
        assert url is not None
        assert url.startswith("http://") or url.startswith("https://")

        vehicle.refresh_from_db()
        assert vehicle.photo
        import os
        assert os.path.exists(vehicle.photo.path)

    def test_vehicle_photo_upload_rejects_large_file(
        self, admin_client, vehicle,
    ):
        big = SimpleUploadedFile(
            "big.png", b"\x00" * (5 * 1024 * 1024 + 1),
            content_type="image/png",
        )
        resp = admin_client.post(
            f"/api/v1/fleet/vehicles/{vehicle.id}/photo/",
            {"photo": big}, format="multipart",
        )
        assert resp.status_code == 400, resp.content

    def test_vehicle_photo_upload_rejects_non_image(
        self, admin_client, vehicle,
    ):
        pdf = SimpleUploadedFile(
            "doc.pdf", b"%PDF-1.4\n...", content_type="application/pdf",
        )
        resp = admin_client.post(
            f"/api/v1/fleet/vehicles/{vehicle.id}/photo/",
            {"photo": pdf}, format="multipart",
        )
        assert resp.status_code == 400


# ─── Documents ZIP export ───

class TestVehicleDocumentsZipExport:
    def test_vehicle_documents_export_zip_structure(
        self, admin_client, tenant, vehicle,
    ):
        for i, dtype in enumerate(("insurance", "registration", "inspection")):
            VehicleDocument.objects.create(
                tenant=tenant, vehicle=vehicle,
                type=dtype,
                document_number=f"DOC-{i:03d}",
                file=SimpleUploadedFile(
                    f"d{i}.pdf", b"PDF-fake-content-" + bytes([i]),
                    content_type="application/pdf",
                ),
            )
        resp = admin_client.get(
            f"/api/v1/fleet/vehicles/{vehicle.id}/documents/export/",
        )
        assert resp.status_code == 200, resp.content
        assert resp["Content-Type"] == "application/zip"
        assert "attachment" in resp["Content-Disposition"]
        assert f"vehicle_{vehicle.plate_number}" in resp["Content-Disposition"]

        buf = io.BytesIO(b"".join(resp.streaming_content)
                         if hasattr(resp, "streaming_content") else resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert len(names) == 3

    def test_vehicle_documents_export_empty(self, admin_client, vehicle):
        resp = admin_client.get(
            f"/api/v1/fleet/vehicles/{vehicle.id}/documents/export/",
        )
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/zip"
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            assert zf.namelist() == []
