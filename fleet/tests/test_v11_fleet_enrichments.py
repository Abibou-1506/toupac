"""TOUPAC Fleet — Tests dette V1.1 Vagues 3+4.

Couvre :
- ``VehicleType.default_seat_map`` : nested ``SeatMapMini`` + ``default_seat_map_id``
  write-only (dette V1.1 Vague 3 — combobox UI frontend).
- ``VehicleType.wheelbase_mm`` + ``axles_count`` : nouveaux champs blueprint SVG
  exposés par le serializer (nullable additif).
- ``DriverFilterSet`` : ``license_classes`` (ArrayField overlap, CSV) +
  ``is_assigned`` (true/false via reverse FK Exists) + ``status`` (non-régression).
"""
import pytest
from rest_framework.test import APIClient

from fleet.models import Driver, Vehicle, VehicleType
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import SeatMap

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Fixtures ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="V11 Fleet", slug="v11-fleet")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin@v11-fleet.sn", password=PASSWORD,
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
def seat_map(tenant):
    return SeatMap.objects.create(
        tenant=tenant, name="Bus 45 places", total_seats=45,
        layout={"rows": 15, "cols": 3}, is_template=False,
    )


@pytest.fixture
def vehicle_type(tenant):
    return VehicleType.objects.create(
        tenant=tenant, name="Bus 45", short="B45",
        category=VehicleType.Category.INTERURBAIN,
        default_capacity=45,
        permit_required=VehicleType.PermitRequired.D,
    )


# ─── VehicleType.default_seat_map ───

class TestVehicleTypeDefaultSeatMap:
    def test_vehicle_type_default_seat_map_nested(
        self, admin_client, tenant, seat_map, vehicle_type,
    ):
        """GET détail → nested ``SeatMapMini`` quand FK posée."""
        vehicle_type.default_seat_map = seat_map
        vehicle_type.save(update_fields=["default_seat_map"])

        resp = admin_client.get(f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/")
        assert resp.status_code == 200, resp.content
        nested = resp.data["default_seat_map"]
        assert nested is not None
        assert nested["id"] == str(seat_map.id)
        assert nested["name"] == "Bus 45 places"
        assert nested["total_seats"] == 45
        assert nested["is_template"] is False

    def test_vehicle_type_default_seat_map_patch(
        self, admin_client, tenant, seat_map, vehicle_type,
    ):
        """PATCH ``default_seat_map_id`` → nested reflète en re-GET."""
        resp = admin_client.patch(
            f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/",
            {"default_seat_map_id": str(seat_map.id)},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["default_seat_map"]["id"] == str(seat_map.id)

        vehicle_type.refresh_from_db()
        assert vehicle_type.default_seat_map_id == seat_map.id

        resp = admin_client.get(f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/")
        assert resp.data["default_seat_map"]["total_seats"] == 45

    def test_vehicle_type_wheelbase_axles_fields_exposed(
        self, admin_client, tenant, vehicle_type,
    ):
        """Les 2 champs blueprint SVG apparaissent dans la réponse (null si
        non définis, int si posés)."""
        resp = admin_client.get(f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/")
        assert resp.status_code == 200
        assert "wheelbase_mm" in resp.data
        assert "axles_count" in resp.data
        assert resp.data["wheelbase_mm"] is None
        assert resp.data["axles_count"] is None

        # Set and re-GET
        resp = admin_client.patch(
            f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/",
            {"wheelbase_mm": 5500, "axles_count": 2},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["wheelbase_mm"] == 5500
        assert resp.data["axles_count"] == 2


# ─── DriverFilterSet ───

@pytest.fixture
def driver_factory(tenant):
    def _make(suffix, license_classes, status=Driver.Status.AVAILABLE):
        user = User.objects.create_user(
            email=f"drv-{suffix}@v11-fleet.sn", password=PASSWORD,
            first_name=f"Drv{suffix}", last_name="Test",
            tenant=tenant, role=User.Role.DRIVER,
        )
        return Driver.objects.create(
            tenant=tenant, user=user,
            matricule=f"TPC-V11-{suffix}",
            license_number=f"SN-DL-{suffix}",
            license_class=(license_classes[0] if license_classes else ""),
            license_classes=license_classes,
            status=status,
        )
    return _make


class TestDriverFilterSet:
    def test_driver_filterset_license_classes_overlap(
        self, admin_client, driver_factory,
    ):
        """``?license_classes=B`` → chauffeurs ayant 'B' dans leur ArrayField."""
        d_b = driver_factory("001", ["B"])
        d_d = driver_factory("002", ["D"])
        d_bd = driver_factory("003", ["B", "D"])

        resp = admin_client.get("/api/v1/fleet/drivers/?license_classes=B")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert str(d_b.id) in ids
        assert str(d_bd.id) in ids
        assert str(d_d.id) not in ids

    def test_driver_filterset_license_classes_csv(
        self, admin_client, driver_factory,
    ):
        """``?license_classes=B,C`` → chauffeurs ayant au moins B ou C."""
        d_b = driver_factory("010", ["B"])
        d_c = driver_factory("011", ["C"])
        d_d = driver_factory("012", ["D"])

        resp = admin_client.get("/api/v1/fleet/drivers/?license_classes=B,C")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert str(d_b.id) in ids
        assert str(d_c.id) in ids
        assert str(d_d.id) not in ids

    def test_driver_filterset_is_assigned_true(
        self, admin_client, tenant, driver_factory,
    ):
        """``?is_assigned=true`` → chauffeurs ayant au moins un véhicule
        affecté via ``Vehicle.assigned_driver``."""
        d_assigned = driver_factory("020", ["D"])
        d_free = driver_factory("021", ["D"])  # noqa: F841 — baseline
        Vehicle.objects.create(
            tenant=tenant, plate_number="DK-9001-AA", capacity=45,
            assigned_driver=d_assigned,
        )

        resp = admin_client.get("/api/v1/fleet/drivers/?is_assigned=true")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert ids == {str(d_assigned.id)}

    def test_driver_filterset_is_assigned_false(
        self, admin_client, tenant, driver_factory,
    ):
        """``?is_assigned=false`` → chauffeurs non affectés."""
        d_assigned = driver_factory("030", ["D"])
        d_free = driver_factory("031", ["D"])
        Vehicle.objects.create(
            tenant=tenant, plate_number="DK-9002-AA", capacity=45,
            assigned_driver=d_assigned,
        )

        resp = admin_client.get("/api/v1/fleet/drivers/?is_assigned=false")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert str(d_free.id) in ids
        assert str(d_assigned.id) not in ids

    def test_driver_filterset_status_still_works(
        self, admin_client, driver_factory,
    ):
        """Le filtre ``status`` historique n'est pas régressé."""
        d_av = driver_factory("040", ["D"], status=Driver.Status.AVAILABLE)
        d_off = driver_factory("041", ["D"], status=Driver.Status.OFF_DUTY)

        resp = admin_client.get("/api/v1/fleet/drivers/?status=off_duty")
        assert resp.status_code == 200
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        ids = {d["id"] for d in data}
        assert str(d_off.id) in ids
        assert str(d_av.id) not in ids
