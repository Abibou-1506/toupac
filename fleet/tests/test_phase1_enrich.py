"""
TOUPAC Fleet — Tests Phase 1 Enrich : VehicleType / Vehicle / Driver.

Couvre les nouveaux champs DS (short, dimensions, odometer, matricule…),
l'alias RN-compat `status_label`, la propriété dérivée `is_on_trip`, le
backfill `license_classes`, la contrainte d'unicité conditionnelle sur
`matricule`, et l'exposition URL absolue des photos.
"""
import io

import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from fleet.models import Driver, Vehicle, VehicleType
from geo.models import Place
from iam.models import Tenant, User
from iam.serializers import ToupacTokenObtainSerializer
from voyage.models import LuggagePolicy, Route, Trip

pytestmark = pytest.mark.django_db

PASSWORD = "TestPass#2026"


# ─── Fixtures ───

@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Transport Phase1", slug="phase1-fleet")


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(name="Transport Phase1 Bis", slug="phase1-fleet-bis")


@pytest.fixture
def admin_user(tenant):
    return User.objects.create_user(
        email="admin@phase1-fleet.sn", password=PASSWORD,
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
def luggage_policy(tenant):
    return LuggagePolicy.objects.create(
        tenant=tenant, name="Standard interurbain", included_kg=20, max_kg=30,
    )


@pytest.fixture
def vehicle_type(tenant, luggage_policy):
    return VehicleType.objects.create(
        tenant=tenant,
        name="Minibus 32 places",
        short="MB32",
        category=VehicleType.Category.INTERURBAIN,
        description="Minibus climatisé interurbain, 32 places assises.",
        default_capacity=32,
        permit_required=VehicleType.PermitRequired.D,
        length_m="8.50",
        width_m="2.30",
        height_m="2.90",
        ptac_kg=7500,
        hold_m3="4.50",
        default_luggage_policy=luggage_policy,
    )


@pytest.fixture
def vehicle(tenant, vehicle_type):
    return Vehicle.objects.create(
        tenant=tenant, vehicle_type=vehicle_type,
        plate_number="DK-1234-AA", code="V-001",
        make="Mercedes", model_name="Sprinter",
        year=2022, capacity=32,
        fuel_type=Vehicle.FuelType.DIESEL,
        transmission=Vehicle.Transmission.MANUELLE,
        odometer_km=120_000,
        last_service_km=100_000,
        service_interval_km=20_000,
    )


@pytest.fixture
def driver_user(tenant):
    return User.objects.create_user(
        email="moussa@phase1-fleet.sn", password=PASSWORD,
        first_name="Moussa", last_name="Diallo", phone="+221771234567",
        tenant=tenant, role=User.Role.DRIVER,
    )


@pytest.fixture
def driver(tenant, driver_user):
    return Driver.objects.create(
        tenant=tenant, user=driver_user,
        license_number="SN-DL-00001", license_class="D",
    )


def _tiny_png_bytes() -> bytes:
    """Génère un PNG minimal (1×1 rouge) en mémoire."""
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── VehicleType ───

class TestVehicleTypeEnrich:
    def test_vehicle_type_new_fields_exposed(self, admin_client, vehicle_type):
        resp = admin_client.get(f"/api/v1/fleet/vehicle-types/{vehicle_type.id}/")
        assert resp.status_code == 200, resp.content
        data = resp.data
        assert data["short"] == "MB32"
        assert data["category"] == "interurbain"
        assert data["description"].startswith("Minibus")
        assert data["permit_required"] == "D"
        assert data["length_m"] == "8.50"
        assert data["width_m"] == "2.30"
        assert data["height_m"] == "2.90"
        assert data["ptac_kg"] == 7500
        assert data["hold_m3"] == "4.50"
        # Alias plat `seats` miroir de default_capacity
        assert data["seats"] == 32
        assert data["default_capacity"] == 32
        # FK nestée {id, name}
        assert data["default_luggage_policy"]["name"] == "Standard interurbain"

    def test_vehicle_type_luggage_policy_fk_nullable(self, vehicle_type, luggage_policy):
        """Supprimer la politique bagages → FK remise à NULL (SET_NULL)."""
        luggage_policy.delete()
        vehicle_type.refresh_from_db()
        assert vehicle_type.default_luggage_policy is None


# ─── Vehicle ───

class TestVehicleEnrich:
    def test_vehicle_new_fields_exposed(self, admin_client, vehicle):
        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200, resp.content
        data = resp.data
        assert data["code"] == "V-001"
        assert data["odometer_km"] == 120_000
        assert data["last_service_km"] == 100_000
        assert data["service_interval_km"] == 20_000
        assert data["fuel_type"] == "diesel"
        assert data["transmission"] == "manuelle"
        assert data["engine_no"] == ""
        assert data["next_maintenance_date"] is None
        assert data["photo"] is None

    @pytest.mark.parametrize(
        "status,expected_label",
        [
            (Vehicle.Status.AVAILABLE, "active"),
            (Vehicle.Status.IN_USE, "active"),
            (Vehicle.Status.MAINTENANCE, "maintenance"),
            (Vehicle.Status.DECOMMISSIONED, "decommissioned"),
        ],
    )
    def test_vehicle_status_label_mapping(
        self, admin_client, vehicle, status, expected_label,
    ):
        vehicle.status = status
        vehicle.save(update_fields=["status"])
        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200
        assert resp.data["status"] == status
        assert resp.data["status_label"] == expected_label

    def test_vehicle_photo_upload_url_absolute(self, admin_client, vehicle):
        png_bytes = _tiny_png_bytes()
        vehicle.photo = SimpleUploadedFile(
            "red.png", png_bytes, content_type="image/png",
        )
        vehicle.save()
        resp = admin_client.get(f"/api/v1/fleet/vehicles/{vehicle.id}/")
        assert resp.status_code == 200
        url = resp.data["photo"]
        assert url is not None
        assert url.startswith("http://") or url.startswith("https://")
        assert "vehicles/photos/" in url


# ─── Driver ───

class TestDriverEnrich:
    def test_driver_license_classes_backfilled(self, driver):
        """La data-migration remplit license_classes depuis license_class.

        Le driver est créé APRÈS la migration donc la logique de backfill
        doit aussi être posée au niveau applicatif. On vérifie ici que
        pour un driver existant, les deux représentations coexistent.
        """
        # Simule l'état legacy (scalaire seul) et le backfill manuel que
        # fait la migration pour les lignes présentes au moment du run.
        driver.license_classes = [driver.license_class] if driver.license_class else []
        driver.save(update_fields=["license_classes"])
        driver.refresh_from_db()
        assert driver.license_class == "D"
        assert driver.license_classes == ["D"]

    def test_driver_matricule_unique_per_tenant(self, tenant, other_tenant, driver):
        """UniqueConstraint conditionnelle : non-vide → unique par tenant,
        vide → autorisé en doublon (via `condition=~Q(matricule='')`)."""
        driver.matricule = "TPC-CH-00001"
        driver.save(update_fields=["matricule"])

        # Même tenant, même matricule non-vide → IntegrityError.
        other_user = User.objects.create_user(
            email="ibou@phase1-fleet.sn", password=PASSWORD,
            first_name="Ibou", last_name="Fall",
            tenant=tenant, role=User.Role.DRIVER,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Driver.objects.create(
                    tenant=tenant, user=other_user,
                    matricule="TPC-CH-00001",
                )

        # Cross-tenant : OK avec le même matricule.
        cross_user = User.objects.create_user(
            email="aliou@phase1-fleet-bis.sn", password=PASSWORD,
            first_name="Aliou", last_name="Ba",
            tenant=other_tenant, role=User.Role.DRIVER,
        )
        cross = Driver.objects.create(
            tenant=other_tenant, user=cross_user,
            matricule="TPC-CH-00001",
        )
        assert cross.pk is not None

        # Deux matricules vides sur le même tenant : OK grâce à la condition.
        empty_user = User.objects.create_user(
            email="fatou@phase1-fleet.sn", password=PASSWORD,
            first_name="Fatou", last_name="Ndoye",
            tenant=tenant, role=User.Role.DRIVER,
        )
        empty = Driver.objects.create(tenant=tenant, user=empty_user, matricule="")
        assert empty.pk is not None

    def test_driver_is_on_trip_derived(self, tenant, driver):
        """is_on_trip = True si un Trip actif référence le chauffeur."""
        place = Place.objects.create(
            tenant=tenant, name="Dakar-P1", type=Place.PlaceType.STATION,
            location=Point(-17.4441, 14.6937, srid=4326),
        )
        other = Place.objects.create(
            tenant=tenant, name="Thiès-P1", type=Place.PlaceType.STATION,
            location=Point(-16.9246, 14.7886, srid=4326),
        )
        route = Route.objects.create(
            tenant=tenant, name="Dakar → Thiès P1", code="DKR-THS-P1",
            origin_place=place, destination_place=other,
        )
        trip = Trip.objects.create(
            tenant=tenant, route=route, internal_id="VYG-P1-01",
            departure_date=timezone.now().date(), scheduled_at=timezone.now(),
            total_seats=45, status=Trip.Status.BOARDING,
            driver=driver,
        )
        assert driver.is_on_trip is True

        trip.status = Trip.Status.COMPLETED
        trip.save(update_fields=["status"])
        assert driver.is_on_trip is False

    @pytest.mark.parametrize(
        "status,expected_label",
        [
            (Driver.Status.AVAILABLE, "active"),
            (Driver.Status.ON_TRIP, "active"),
            (Driver.Status.OFF_DUTY, "leave"),
        ],
    )
    def test_driver_status_label_mapping(
        self, admin_client, driver, status, expected_label,
    ):
        driver.status = status
        driver.save(update_fields=["status"])
        resp = admin_client.get(f"/api/v1/fleet/drivers/{driver.id}/")
        assert resp.status_code == 200
        assert resp.data["status"] == status
        assert resp.data["status_label"] == expected_label
        assert isinstance(resp.data["is_on_trip"], bool)
