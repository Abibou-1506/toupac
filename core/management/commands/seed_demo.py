"""
TOUPAC — Jeu de données de démonstration.

Deux compagnies plausibles (une longue distance, une urbaine/interurbaine) avec
un historique vécu : voyages passés clôturés, deux voyages en cours, des
voyages à venir. Sert aux tests fonctionnels via l'admin et Swagger, à la démo,
et de backend cible pour l'app contrôleur React Native.

Idempotent : `get_or_create` partout, sauf réservations / events de contrôle /
encaissements, dédupliqués par clé fonctionnelle (« ce voyage a déjà des
réservations → on passe »), leurs contraintes uniques conditionnelles rendant
un get_or_create ni lisible ni fiable.

    python manage.py seed_demo
    python manage.py seed_demo --reset          # purge + regénère (confirmation)
    python manage.py seed_demo --only voyage    # une seule famille
    python manage.py seed_demo --quiet          # CI
"""
import math
import random
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import Invoice, InvoiceLine, Payment, PriceList, PriceRule
from billing.services import InvoiceGenerator
from colis.models import DeliveryTask, Order, Parcel, ProofOfDelivery
from fleet.models import Driver, Fleet, FleetVehicle, Vehicle, VehicleDocument, VehicleType
from geo.models import Place
from iam.models import Tenant, User
from notifications.models import NotificationLog, NotificationTemplate
from tracking.models import Geofence, Position, TrackingLink
from voyage.models import (
    Anomaly,
    CashEntry,
    ControlEvent,
    Controller,
    ControlSession,
    Incident,
    LuggagePolicy,
    Passenger,
    Reservation,
    Route,
    RouteStop,
    Schedule,
    SeatMap,
    Trip,
    TripStop,
)
from voyage.services.qr_jwt import sign_ticket_jwt
from workflow.models import WorkflowDefinition

DEMO_PASSWORD = "Toupac2026!"
RANDOM_SEED = 42

FAMILIES = [
    "tenants", "places", "users", "fleet", "voyage",
    "colis", "billing", "tracking", "notifications",
]

# ─── Référentiel ───

TENANTS = [
    {"slug": "sahel-express", "name": "Transport Sahel Express", "prefix": "SE",
     "subscription_plan": Tenant.Plan.PRO},
    {"slug": "dem-dikk", "name": "Dem Dikk Express", "prefix": "DD",
     "subscription_plan": Tenant.Plan.STARTER},
]

PLACES = [
    ("Gare Routière Pompiers", "Dakar", "SN", 14.6937, -17.4441),
    ("Gare Routière Baux Maraîchers", "Dakar", "SN", 14.7597, -17.3660),
    ("Gare Routière Thiès", "Thiès", "SN", 14.7910, -16.9358),
    ("Gare Routière Kaolack", "Kaolack", "SN", 14.1520, -16.0726),
    ("Gare Routière Tambacounda", "Tambacounda", "SN", 13.7707, -13.6673),
    ("Gare Routière Kayes", "Kayes", "ML", 14.4469, -11.4453),
    ("Gare Routière Sogoniko", "Bamako", "ML", 12.6098, -7.9739),
    ("Gare Routière Ziguinchor", "Ziguinchor", "SN", 12.5833, -16.2719),
]

USERS = {
    "sahel-express": [
        ("admin@sahel-express.sn", "Fatou", "Sarr", User.Role.ADMIN),
        ("dispatcher@sahel-express.sn", "Ibrahima", "Diop", User.Role.DISPATCHER),
        ("agent@sahel-express.sn", "Awa", "Ndiaye", User.Role.AGENT),
        ("controller1@sahel-express.sn", "Modou", "Fall", User.Role.CONTROLLER),
        ("controller2@sahel-express.sn", "Aïssatou", "Ba", User.Role.CONTROLLER),
        ("driver1@sahel-express.sn", "Moussa", "Diallo", User.Role.DRIVER),
        ("driver2@sahel-express.sn", "Ousmane", "Sy", User.Role.DRIVER),
    ],
    "dem-dikk": [
        ("admin@dem-dikk.sn", "Mariama", "Camara", User.Role.ADMIN),
        ("dispatcher@dem-dikk.sn", "Cheikh", "Ndiaye", User.Role.DISPATCHER),
        ("agent@dem-dikk.sn", "Fatoumata", "Kane", User.Role.AGENT),
        ("controller1@dem-dikk.sn", "Mamadou", "Faye", User.Role.CONTROLLER),
        ("controller2@dem-dikk.sn", "Ndeye", "Gueye", User.Role.CONTROLLER),
        ("driver1@dem-dikk.sn", "Alioune", "Fall", User.Role.DRIVER),
        ("driver2@dem-dikk.sn", "Bineta", "Cissé", User.Role.DRIVER),
    ],
}

VEHICLE_TYPES = [
    ("Autocar 45 places", 45, "diesel", {"rows": 12, "cols": 4}),
    ("Minicar 30 places", 30, "diesel", {"rows": 10, "cols": 3}),
    ("Minibus 15 places", 15, "essence", {"rows": 5, "cols": 3}),
]

VEHICLES = {
    "sahel-express": [
        ("SN-2145-AZ", "Mercedes-Benz", "Tourismo 15 RHD", 2019, "Autocar 45 places", 45, "trc-se-01"),
        ("SN-2146-AZ", "Mercedes-Benz", "Tourismo 15 RHD", 2020, "Autocar 45 places", 45, "trc-se-02"),
        ("SN-1044-BK", "Toyota", "Coaster", 2021, "Minicar 30 places", 30, "trc-se-03"),
    ],
    "dem-dikk": [
        ("DK-DD-01", "Iveco", "Crossway", 2022, "Autocar 45 places", 45, "trc-dd-01"),
        ("DK-DD-02", "Toyota", "Coaster", 2021, "Minicar 30 places", 30, "trc-dd-02"),
        ("DK-DD-03", "Toyota", "Coaster", 2020, "Minicar 30 places", 30, "trc-dd-03"),
        ("DK-DD-04", "Nissan", "Urvan", 2023, "Minibus 15 places", 15, "trc-dd-04"),
    ],
}

# Gare de rattachement par tenant (les véhicules et chauffeurs gravitent autour).
HOME_PLACE = {"sahel-express": "Gare Routière Pompiers", "dem-dikk": "Gare Routière Baux Maraîchers"}

DRIVERS = {
    "sahel-express": [("driver1@sahel-express.sn", "D", Decimal("95.00")),
                      ("driver2@sahel-express.sn", "D", Decimal("88.50"))],
    "dem-dikk": [("driver1@dem-dikk.sn", "D", Decimal("92.00")),
                 ("driver2@dem-dikk.sn", "D", Decimal("97.50"))],
}

FLEETS = {
    "sahel-express": ("Flotte Longue Distance", "Sahel"),
    "dem-dikk": ("Flotte Urbaine et Interurbaine", "Dakar"),
}

LUGGAGE_POLICIES = {
    "sahel-express": [
        ("Bagage standard 20kg", 20, 40, 1500, 2),
        ("Bagage express 30kg", 30, 50, 1000, 3),
    ],
    "dem-dikk": [
        ("Bagage urbain 10kg", 10, 25, 500, 2),
        ("Bagage voyageur 20kg", 20, 35, 800, 2),
    ],
}

# code, nom, origine, destination, km, minutes, politique bagages,
# escales [(place, offset, boarding, alighting)]
ROUTES = {
    "sahel-express": [
        ("DKR-BKO", "Dakar → Bamako", "Gare Routière Pompiers", "Gare Routière Sogoniko",
         1450, 1440, "Bagage standard 20kg", [
             ("Gare Routière Pompiers", 0, True, False),
             ("Gare Routière Kaolack", 180, True, True),
             ("Gare Routière Tambacounda", 600, True, True),
             ("Gare Routière Kayes", 1080, True, True),
             ("Gare Routière Sogoniko", 1440, False, True),
         ]),
        ("DKR-ZIG", "Dakar → Ziguinchor", "Gare Routière Pompiers", "Gare Routière Ziguinchor",
         460, 480, "Bagage standard 20kg", [
             ("Gare Routière Pompiers", 0, True, False),
             ("Gare Routière Kaolack", 180, True, True),
             ("Gare Routière Ziguinchor", 480, False, True),
         ]),
        ("BKO-DKR", "Bamako → Dakar", "Gare Routière Sogoniko", "Gare Routière Pompiers",
         1450, 1440, "Bagage standard 20kg", [
             ("Gare Routière Sogoniko", 0, True, False),
             ("Gare Routière Kayes", 360, True, True),
             ("Gare Routière Tambacounda", 840, True, True),
             ("Gare Routière Kaolack", 1260, True, True),
             ("Gare Routière Pompiers", 1440, False, True),
         ]),
    ],
    "dem-dikk": [
        # Route directe, sans escale intermédiaire — cas volontairement couvert.
        ("DKR-THI", "Dakar → Thiès", "Gare Routière Baux Maraîchers", "Gare Routière Thiès",
         70, 90, "Bagage urbain 10kg", [
             ("Gare Routière Baux Maraîchers", 0, True, False),
             ("Gare Routière Thiès", 90, False, True),
         ]),
        ("DKR-KLK", "Dakar → Kaolack", "Gare Routière Baux Maraîchers", "Gare Routière Kaolack",
         190, 210, "Bagage voyageur 20kg", [
             ("Gare Routière Baux Maraîchers", 0, True, False),
             ("Gare Routière Thiès", 90, True, True),
             ("Gare Routière Kaolack", 210, False, True),
         ]),
        ("KLK-DKR", "Kaolack → Dakar", "Gare Routière Kaolack", "Gare Routière Baux Maraîchers",
         190, 210, "Bagage voyageur 20kg", [
             ("Gare Routière Kaolack", 0, True, False),
             ("Gare Routière Thiès", 120, True, True),
             ("Gare Routière Baux Maraîchers", 210, False, True),
         ]),
    ],
}

SCHEDULES = {
    "sahel-express": [
        ("DKR-BKO", time(18, 0), [1, 3, 5], 25000),
        ("DKR-ZIG", time(7, 0), [0, 2, 4, 6], 12000),
        ("BKO-DKR", time(15, 0), [1, 3, 5], 25000),
    ],
    "dem-dikk": [
        ("DKR-THI", time(6, 0), [0, 1, 2, 3, 4, 5, 6], 1500),
        ("DKR-THI", time(18, 0), [0, 1, 2, 3, 4, 5, 6], 1500),
        ("DKR-KLK", time(8, 0), [0, 1, 2, 3, 4, 5, 6], 4500),
        ("KLK-DKR", time(15, 0), [0, 1, 2, 3, 4, 5, 6], 4500),
    ],
}

CONTROLLERS = {
    "sahel-express": [
        ("controller1@sahel-express.sn", "CTRL-SE-01", "Dakar Pompiers"),
        ("controller2@sahel-express.sn", "CTRL-SE-02", "Dakar Pompiers"),
    ],
    "dem-dikk": [
        ("controller1@dem-dikk.sn", "CTRL-DD-01", "Baux Maraîchers"),
        ("controller2@dem-dikk.sn", "CTRL-DD-02", "Baux Maraîchers"),
    ],
}

PASSENGER_FIRST = [
    "Abdoulaye", "Aminata", "Babacar", "Coumba", "Daouda", "Fatou", "Ibrahima", "Khady",
    "Lamine", "Mariama", "Ndeye", "Omar", "Penda", "Racine", "Sokhna", "Thierno",
    "Yacine", "Adama", "Bocar", "Dieynaba",
]
PASSENGER_LAST = [
    "Fall", "Sarr", "Diop", "Ndiaye", "Ba", "Diallo", "Cissé", "Kane",
    "Sow", "Camara", "Sagna", "Mbengue", "Faye", "Gueye", "Sy", "Thiam",
]

# is_staff seul ne donne accès à rien : l'admin Django exige des permissions
# par modèle. Ce groupe les accorde sur les apps métier (sans delete) pour que
# les comptes de démo puissent réellement parcourir les données.
STAFF_GROUP = "Démo — Personnel compagnie"
STAFF_GROUP_APPS = ["voyage", "colis", "billing", "fleet", "geo", "tracking", "notifications", "workflow"]

NOTIFICATION_TEMPLATES = [
    ("reservation_confirmed", "sms", "",
     "Bonjour {{nom}}, votre réservation {{trip_code}} le {{date}} est confirmée. "
     "Siège {{seat}}. Bon voyage."),
    ("trip_reminder", "sms", "",
     "Rappel: votre bus {{trip_code}} part demain à {{time}}. Présentez-vous 30 min avant."),
    ("parcel_delivered", "sms", "",
     "Votre colis {{tracking}} a été livré à {{recipient}} le {{date}}."),
    ("payment_received", "email", "Paiement reçu — TOUPAC",
     "Merci pour votre paiement de {{amount}} XOF."),
]

# Ordre de purge : enfants d'abord, pour ne pas buter sur les FK PROTECT
# (Trip→Route, TripStop→RouteStop, ControlSession/CashEntry→Controller,
# Incident→User). La suppression du Tenant en fin de liste balaie le reste.
RESET_ORDER = [
    CashEntry, Incident, Anomaly, ControlEvent, ControlSession, Controller,
    ProofOfDelivery, DeliveryTask, Parcel, Order,
    Payment, InvoiceLine, Invoice, PriceRule, PriceList,
    Position, Geofence, TrackingLink, NotificationLog,
    TripStop, Reservation, Trip, Schedule, RouteStop, Route,
    Passenger, SeatMap, LuggagePolicy,
    FleetVehicle, Fleet, VehicleDocument, Vehicle, Driver, VehicleType,
]

# Modèles sans FK tenant directe (rattachés via leur parent).
TENANT_PATH = {FleetVehicle: "fleet__tenant", InvoiceLine: "invoice__tenant"}


def seat_labels(layout, total_seats):
    """Étiquettes de sièges, dans le même ordre que TripViewSet._build_seat_occupation."""
    rows = (layout or {}).get("rows") or 0
    cols = (layout or {}).get("cols") or 0
    labels = [f"{chr(64 + c)}{r}" for r in range(1, rows + 1) for c in range(1, cols + 1)]
    return labels[:total_seats]


def phone():
    return f"+2217{random.choice('78')}{random.randint(1000000, 9999999)}"


def jitter(lon, lat, spread=0.005):
    return Point(lon + random.uniform(-spread, spread), lat + random.uniform(-spread, spread), srid=4326)


def octagon(lon, lat, radius_m=200):
    """Octogone régulier approchant un cercle — évite une dépendance à shapely."""
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat)))
    points = [
        (lon + dlon * math.cos(math.radians(45 * i)), lat + dlat * math.sin(math.radians(45 * i)))
        for i in range(8)
    ]
    points.append(points[0])
    return Polygon(points, srid=4326)


def aware(day: date, at: time):
    return timezone.make_aware(datetime.combine(day, at), timezone.get_current_timezone())


class Command(BaseCommand):
    help = "Génère un jeu de données de démonstration complet sur 2 tenants."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Purge les données de démo avant de regénérer (confirmation requise).")
        parser.add_argument("--only", choices=[*FAMILIES, "all"], default="all",
                            help="Ne seede qu'une famille.")
        parser.add_argument("--quiet", action="store_true",
                            help="N'affiche que les avertissements et le récapitulatif.")

    # ─── Sortie ───

    def log(self, message):
        if not self.quiet:
            self.stdout.write(message)

    def warn(self, message):
        self.stdout.write(self.style.WARNING(f"⚠️  {message}"))

    def step(self, label, summary):
        self.position += 1
        self.log(f"[{self.position}/{self.total_steps}] ✓ {label}: {summary}")

    @staticmethod
    def counts(created, existing):
        return f"{created} créé(s), {existing} déjà présent(s)"

    @staticmethod
    def rng(namespace):
        """
        Générateur déterministe et indépendant du flux global.

        Tout ce qui alimente une clé d'identité (dates de voyage → internal_id,
        nombre de colis → tracking_number) doit passer par ici : sur un second
        run, les objets déjà présents court-circuitent des appels à random(),
        le flux global se décale, et les clés changeraient — créant des
        doublons au lieu de retomber sur l'existant.
        """
        return random.Random(f"{RANDOM_SEED}-{namespace}")

    # ─── Entrée ───

    def handle(self, *args, **options):
        random.seed(RANDOM_SEED)
        self.quiet = options["quiet"]
        only = options["only"]
        families = FAMILIES if only == "all" else [only]
        self.position = 0
        self.total_steps = len(families)

        if options["reset"]:
            self.confirm_reset()
            self.do_reset()

        if not WorkflowDefinition.objects.exists():
            self.warn("Aucun workflow défini — lancez `python manage.py seed_workflows`. "
                      "Le seed continue sans.")

        if not getattr(settings, "TOUPAC_QR_PRIVATE_KEY_PEM", ""):
            self.warn("TOUPAC_QR_PRIVATE_KEY_PEM absente : les QR seront signés avec une keypair "
                      "ÉPHÉMÈRE et deviendront invérifiables au prochain redémarrage du process. "
                      "Pour une démo durable : python scripts/generate_qr_keypair.py --out-dir ./secrets/")

        seeders = {
            "tenants": self.seed_tenants, "places": self.seed_places, "users": self.seed_users,
            "fleet": self.seed_fleet, "voyage": self.seed_voyage, "colis": self.seed_colis,
            "billing": self.seed_billing, "tracking": self.seed_tracking,
            "notifications": self.seed_notifications,
        }
        for family in families:
            seeders[family]()

        self.print_summary()

    # ─── Reset ───

    def confirm_reset(self):
        self.stdout.write(self.style.WARNING(
            "⚠️  Cette commande va supprimer TOUTES les données de démo (tenants "
            "'sahel-express' et 'dem-dikk', users, trips, etc.). Les données seront perdues."
        ))
        answer = input("Tapez 'RESET DEMO' pour confirmer : ")
        if answer.strip() != "RESET DEMO":
            raise CommandError("Confirmation incorrecte — abandon, rien n'a été supprimé.")

    @transaction.atomic
    def do_reset(self):
        tenants = list(Tenant.objects.filter(slug__in=[t["slug"] for t in TENANTS]))
        if not tenants:
            self.log("Rien à purger.")
            return

        deleted = 0
        for model in RESET_ORDER:
            path = TENANT_PATH.get(model, "tenant")
            count, _ = model.objects.filter(**{f"{path}__in": tenants}).delete()
            deleted += count
        for tenant in tenants:
            count, _ = tenant.delete()
            deleted += count

        # Places publiques et templates système (tenant=None) sont intacts par
        # construction : tous les filtres ci-dessus passent par un tenant.
        self.log(f"Purge : {deleted} objets supprimés.")

    # ─── Helpers de résolution ───

    @staticmethod
    def tenants():
        return list(Tenant.objects.filter(slug__in=[t["slug"] for t in TENANTS]).order_by("slug"))

    @staticmethod
    def prefix_for(tenant):
        return next(t["prefix"] for t in TENANTS if t["slug"] == tenant.slug)

    @staticmethod
    def place(name):
        return Place.objects.get(tenant__isnull=True, name=name)

    def require(self, queryset, label):
        """Dépendance d'une famille sur une autre — avertit plutôt que de planter."""
        if not queryset.exists():
            self.warn(f"{label} absent(s) — lancez d'abord `seed_demo` sans --only.")
            return False
        return True

    # ─── 1. Tenants ───

    def seed_tenants(self):
        created = existing = 0
        for spec in TENANTS:
            # Un tenant homonyme créé à la main lors d'une démo précédente
            # capturerait les objets suivants : on le rattache au bon slug.
            clash = Tenant.objects.filter(name=spec["name"]).exclude(slug=spec["slug"]).first()
            if clash:
                self.warn(f"Tenant « {spec['name']} » trouvé avec le slug '{clash.slug}' — "
                          f"resslugué en '{spec['slug']}'.")
                clash.slug = spec["slug"]
                clash.save(update_fields=["slug", "updated_at"])

            _, was_created = Tenant.objects.get_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"], "country_code": "SN", "currency": "XOF",
                    "timezone": "Africa/Dakar", "language": "fr",
                    "status": Tenant.Status.ACTIVE, "subscription_plan": spec["subscription_plan"],
                },
            )
            created, existing = (created + 1, existing) if was_created else (created, existing + 1)
        self.step("Tenants", self.counts(created, existing))

    # ─── 2. Places (publiques, tenant=None) ───

    def seed_places(self):
        created = existing = 0
        for name, city, country, lat, lon in PLACES:
            _, was_created = Place.objects.get_or_create(
                tenant__isnull=True, name=name,
                defaults={
                    "tenant": None, "city": city, "country_code": country,
                    "type": Place.PlaceType.STATION, "location": Point(lon, lat, srid=4326),
                },
            )
            created, existing = (created + 1, existing) if was_created else (created, existing + 1)
        self.step("Places publiques", self.counts(created, existing))

    # ─── 3. Users ───

    def seed_users(self):
        if not self.require(Tenant.objects.filter(slug__in=USERS), "Tenants"):
            return
        created = existing = 0
        for tenant in self.tenants():
            for email, first, last, role in USERS[tenant.slug]:
                user = User.objects.filter(email=email).first()
                if user:
                    existing += 1
                    continue
                User.objects.create_user(
                    email=email, password=DEMO_PASSWORD, first_name=first, last_name=last,
                    tenant=tenant, role=role, phone=phone(),
                    is_staff=role in (User.Role.ADMIN, User.Role.DISPATCHER), is_active=True,
                )
                created += 1
        staff = self.grant_staff_permissions()
        self.step("Utilisateurs", f"{self.counts(created, existing)}, {staff} rattaché(s) au groupe admin")

    @staticmethod
    def grant_staff_permissions():
        """Rattache les comptes is_staff au groupe de démo (view/add/change, pas delete)."""
        group, _ = Group.objects.get_or_create(name=STAFF_GROUP)
        permissions = Permission.objects.filter(
            content_type__app_label__in=STAFF_GROUP_APPS,
        ).exclude(codename__startswith="delete_")
        group.permissions.set(permissions)

        staff = User.objects.filter(tenant__slug__in=[t["slug"] for t in TENANTS], is_staff=True)
        for user in staff:
            user.groups.add(group)
        return staff.count()

    # ─── 4. Flotte ───

    def seed_fleet(self):
        if not self.require(Tenant.objects.filter(slug__in=USERS), "Tenants"):
            return
        today = timezone.now().date()
        types = vehicles = docs = drivers = fleets = 0

        for tenant in self.tenants():
            home = self.place(HOME_PLACE[tenant.slug])
            home_lon, home_lat = home.location.x, home.location.y

            for name, capacity, fuel, _layout in VEHICLE_TYPES:
                _, was_created = VehicleType.objects.get_or_create(
                    tenant=tenant, name=name,
                    defaults={"default_capacity": capacity, "fuel_type": fuel},
                )
                types += was_created

            for plate, make, model_name, year, type_name, capacity, traccar in VEHICLES[tenant.slug]:
                vehicle, was_created = Vehicle.objects.get_or_create(
                    tenant=tenant, plate_number=plate,
                    defaults={
                        "vehicle_type": VehicleType.objects.get(tenant=tenant, name=type_name),
                        "make": make, "model_name": model_name, "year": year,
                        "capacity": capacity, "status": Vehicle.Status.AVAILABLE,
                        "traccar_device_id": traccar, "location": jitter(home_lon, home_lat),
                    },
                )
                vehicles += was_created

                sanitized = plate.replace("-", "")
                doc_specs = [
                    (VehicleDocument.DocType.INSURANCE, today - timedelta(days=182), today + timedelta(days=182)),
                    (VehicleDocument.DocType.INSPECTION, today - timedelta(days=91), today + timedelta(days=273)),
                    # Expire dans 15 jours : alimente l'alerte check_expiring_documents.
                    (VehicleDocument.DocType.TRANSPORT_PERMIT, today - timedelta(days=350), today + timedelta(days=15)),
                ]
                for doc_type, issued, expires in doc_specs:
                    _, was_created = VehicleDocument.objects.get_or_create(
                        tenant=tenant, vehicle=vehicle, type=doc_type,
                        defaults={
                            "document_number": f"{doc_type.upper()}-{sanitized}-{issued.year}",
                            "issue_date": issued, "expiry_date": expires, "status": "valid",
                        },
                    )
                    docs += was_created

            for index, (email, license_class, score) in enumerate(DRIVERS[tenant.slug], start=1):
                user = User.objects.filter(email=email).first()
                if user is None:
                    continue
                _, was_created = Driver.objects.get_or_create(
                    user=user,
                    defaults={
                        "tenant": tenant,
                        "license_number": f"SN-DL-{self.prefix_for(tenant)}-{index:03d}",
                        "license_class": license_class,
                        "license_expiry": today + timedelta(days=548),
                        "status": Driver.Status.AVAILABLE, "score": score,
                        "last_known_location": jitter(home_lon, home_lat),
                    },
                )
                drivers += was_created

            fleet_name, zone = FLEETS[tenant.slug]
            fleet, was_created = Fleet.objects.get_or_create(
                tenant=tenant, name=fleet_name,
                defaults={"zone": zone,
                          "manager": User.objects.filter(tenant=tenant, role=User.Role.ADMIN).first()},
            )
            fleets += was_created
            for vehicle in Vehicle.objects.filter(tenant=tenant):
                FleetVehicle.objects.get_or_create(fleet=fleet, vehicle=vehicle)

        self.step("Flotte", f"{types} types, {vehicles} véhicules, {docs} documents, "
                            f"{drivers} chauffeurs, {fleets} flottes (nouveaux)")

    # ─── 5. Voyage ───

    def seed_voyage(self):
        if not self.require(Vehicle.objects.all(), "Véhicules"):
            return
        for tenant in self.tenants():
            self._seed_voyage_referential(tenant)
        counts = {
            "routes": Route.objects.count(), "horaires": Schedule.objects.count(),
            "passagers": Passenger.objects.count(),
        }
        trips = reservations = 0
        for tenant in self.tenants():
            made_trips, made_reservations = self._seed_voyage_operations(tenant)
            trips += made_trips
            reservations += made_reservations
        self.step("Voyage", f"{counts['routes']} routes, {counts['horaires']} horaires, "
                            f"{counts['passagers']} passagers, {trips} voyages, "
                            f"{reservations} réservations (nouvelles)")

    def _seed_voyage_referential(self, tenant):
        for name, included, maximum, excess, pieces in LUGGAGE_POLICIES[tenant.slug]:
            LuggagePolicy.objects.get_or_create(
                tenant=tenant, name=name,
                defaults={"included_kg": included, "max_kg": maximum,
                          "excess_price_per_kg_xof": excess, "max_pieces": pieces},
            )

        for type_name, capacity, _fuel, layout in VEHICLE_TYPES:
            vehicle_type = VehicleType.objects.filter(tenant=tenant, name=type_name).first()
            SeatMap.objects.get_or_create(
                tenant=tenant, name=f"Plan {type_name}",
                defaults={"vehicle_type": vehicle_type, "total_seats": capacity, "layout": layout},
            )

        for code, name, origin, destination, km, minutes, policy_name, stops in ROUTES[tenant.slug]:
            route, _ = Route.objects.get_or_create(
                tenant=tenant, code=code,
                defaults={
                    "name": name, "origin_place": self.place(origin),
                    "destination_place": self.place(destination),
                    "distance_km": Decimal(km), "duration_minutes": minutes,
                    "luggage_policy": LuggagePolicy.objects.filter(tenant=tenant, name=policy_name).first(),
                    "is_active": True,
                },
            )
            for order, (place_name, offset, boarding, alighting) in enumerate(stops):
                RouteStop.objects.get_or_create(
                    route=route, stop_order=order,
                    defaults={"tenant": tenant, "place": self.place(place_name),
                              "offset_minutes": offset, "is_boarding": boarding,
                              "is_alighting": alighting},
                )

        for code, departure, days, price in SCHEDULES[tenant.slug]:
            route = Route.objects.filter(tenant=tenant, code=code).first()
            Schedule.objects.get_or_create(
                tenant=tenant, route=route, departure_time=departure,
                defaults={"days_of_week": days, "default_price_xof": price, "is_active": True,
                          "default_vehicle_type": None},
            )

        for email, matricule, agency in CONTROLLERS[tenant.slug]:
            user = User.objects.filter(email=email).first()
            if user is None:
                continue
            Controller.objects.get_or_create(
                user=user,
                defaults={"tenant": tenant, "matricule": matricule, "agency": agency,
                          "status": Controller.Status.ACTIVE},
            )

        wanted = 15 if tenant.slug == "sahel-express" else 20
        for index in range(wanted):
            first = PASSENGER_FIRST[(index * 3 + len(tenant.slug)) % len(PASSENGER_FIRST)]
            last = PASSENGER_LAST[(index * 5 + len(tenant.slug)) % len(PASSENGER_LAST)]
            has_id = index % 10 < 3  # ~30 % avec pièce d'identité
            Passenger.objects.get_or_create(
                tenant=tenant, first_name=first, last_name=last,
                defaults={
                    "phone": phone(),
                    "email": f"{first.lower()}.{last.lower()}{index}@example.sn" if index % 3 == 0 else "",
                    "id_type": "CNI" if has_id else "",
                    "id_number": f"SN-{random.randint(1000000, 9999999)}-{random.randint(10, 99)}" if has_id else "",
                    "nationality": "SN",
                },
            )

    def _trip_plan(self, tenant, now):
        """(route_code, scheduled_at, status, fill_ratio) des voyages à générer."""
        rng = self.rng(f"trips-{tenant.slug}")
        long_haul = tenant.slug == "sahel-express"
        codes = [r[0] for r in ROUTES[tenant.slug]]
        plan = []

        for index in range(5):  # passés
            day = (now - timedelta(days=rng.randint(3, 30))).date()
            code = codes[index % len(codes)]
            departure = next(s[1] for s in SCHEDULES[tenant.slug] if s[0] == code)
            plan.append((code, aware(day, departure), Trip.Status.COMPLETED, rng.uniform(0.6, 0.8)))

        plan.append((codes[0], aware(now.date(), time(18, 0)), Trip.Status.BOARDING, 0.5))
        plan.append((
            codes[0] if long_haul else "DKR-KLK",
            now - timedelta(hours=2) if long_haul else now - timedelta(minutes=30),
            Trip.Status.IN_TRANSIT, 0.6,
        ))
        for index in range(3):  # à venir
            day = (now + timedelta(days=index + 3)).date()
            code = codes[index % len(codes)]
            departure = next(s[1] for s in SCHEDULES[tenant.slug] if s[0] == code)
            plan.append((code, aware(day, departure), Trip.Status.SCHEDULED, rng.uniform(0.1, 0.3)))

        code = codes[0]
        departure = next(s[1] for s in SCHEDULES[tenant.slug] if s[0] == code)
        plan.append((code, aware((now + timedelta(days=2)).date(), departure), Trip.Status.SCHEDULED, 0.9))
        return plan

    def _seed_voyage_operations(self, tenant):
        now = timezone.now()
        prefix = self.prefix_for(tenant)
        vehicles = list(Vehicle.objects.filter(tenant=tenant).order_by("plate_number"))
        drivers = list(Driver.objects.filter(tenant=tenant).order_by("license_number"))
        controllers = list(Controller.objects.filter(tenant=tenant).order_by("matricule"))
        passengers = list(Passenger.objects.filter(tenant=tenant).order_by("last_name", "first_name"))
        if not (vehicles and drivers and controllers and passengers):
            self.warn(f"{tenant.name} : référentiel voyage incomplet, opérations ignorées.")
            return 0, 0

        made_trips = made_reservations = 0
        for index, (code, scheduled_at, status, fill) in enumerate(self._trip_plan(tenant, now)):
            route = Route.objects.filter(tenant=tenant, code=code).first()
            schedule = Schedule.objects.filter(tenant=tenant, route=route).first()
            vehicle = vehicles[index % len(vehicles)]
            driver = drivers[index % len(drivers)]
            seat_map = SeatMap.objects.filter(tenant=tenant, total_seats=vehicle.capacity).first()
            internal_id = f"T-{prefix}-{scheduled_at:%Y%m%d}-{index:02d}"

            defaults = {
                "route": route, "schedule": schedule, "vehicle": vehicle, "driver": driver,
                "seat_map": seat_map, "departure_date": scheduled_at.date(),
                "scheduled_at": scheduled_at, "status": status,
                "total_seats": vehicle.capacity, "booked_seats": 0,
            }
            if status == Trip.Status.COMPLETED:
                defaults["actual_departure_at"] = scheduled_at + timedelta(minutes=random.randint(-5, 30))
                defaults["actual_arrival_at"] = (
                    scheduled_at + timedelta(minutes=route.duration_minutes + random.randint(-30, 90))
                )
            elif status == Trip.Status.IN_TRANSIT:
                defaults["actual_departure_at"] = scheduled_at + timedelta(minutes=random.randint(0, 10))

            trip, was_created = Trip.objects.get_or_create(
                tenant=tenant, internal_id=internal_id, defaults=defaults,
            )
            made_trips += was_created
            self._seed_trip_stops(trip, route, status)
            made_reservations += self._seed_reservations(trip, schedule, passengers, fill, status)
            self._seed_control_session(trip, controllers[index % len(controllers)], status)

        self._seed_incident(tenant, controllers)
        return made_trips, made_reservations

    @staticmethod
    def _seed_trip_stops(trip, route, status):
        route_stops = list(RouteStop.objects.filter(route=route).order_by("stop_order"))
        for position, route_stop in enumerate(route_stops):
            eta = trip.scheduled_at + timedelta(minutes=route_stop.offset_minutes)
            if status == Trip.Status.COMPLETED:
                stop_status = TripStop.Status.ARRIVED if position == len(route_stops) - 1 else TripStop.Status.DEPARTED
            elif status == Trip.Status.IN_TRANSIT:
                # Origine quittée, escales à venir encore en attente.
                stop_status = TripStop.Status.DEPARTED if position == 0 else TripStop.Status.PENDING
            else:
                stop_status = TripStop.Status.PENDING
            TripStop.objects.get_or_create(
                trip=trip, stop_order=route_stop.stop_order,
                defaults={
                    "tenant": trip.tenant, "route_stop": route_stop, "place": route_stop.place,
                    "eta": eta, "status": stop_status,
                    "ata": eta if stop_status in (TripStop.Status.ARRIVED, TripStop.Status.DEPARTED) else None,
                    "atd": eta if stop_status == TripStop.Status.DEPARTED else None,
                },
            )

    @staticmethod
    def _reservation_statuses(status, count):
        """Répartition des statuts selon l'état du voyage."""
        if status == Trip.Status.COMPLETED:
            weights = [(Reservation.Status.BOARDED, 0.70), (Reservation.Status.NO_SHOW, 0.15),
                       (Reservation.Status.REFUSED, 0.05), (Reservation.Status.CANCELLED, 0.10)]
        elif status == Trip.Status.BOARDING:
            weights = [(Reservation.Status.BOOKED, 0.34), (Reservation.Status.CHECKED_IN, 0.33),
                       (Reservation.Status.BOARDED, 0.33)]
        elif status == Trip.Status.IN_TRANSIT:
            weights = [(Reservation.Status.BOARDED, 1.0)]
        else:
            weights = [(Reservation.Status.BOOKED, 1.0)]
        statuses = []
        for value, share in weights:
            statuses.extend([value] * round(count * share))
        while len(statuses) < count:
            statuses.append(weights[0][0])
        return statuses[:count]

    def _seed_reservations(self, trip, schedule, passengers, fill, status):
        # Clé fonctionnelle : les contraintes uniques conditionnelles sur
        # (trip, seat_label) rendent un get_or_create par réservation illisible.
        if trip.reservations.exists():
            return 0

        labels = seat_labels(trip.seat_map.layout if trip.seat_map else {}, trip.total_seats)
        wanted = int(len(labels) * fill)
        if wanted == 0:
            return 0
        price = schedule.default_price_xof if schedule else 5000
        statuses = self._reservation_statuses(status, wanted)
        made = 0

        for index in range(wanted):
            passenger = passengers[index % len(passengers)]
            reservation_status = statuses[index]
            method = random.choice(["wave", "orange_money", "cash", "onboard_cash"])
            reservation = Reservation.objects.create(
                tenant=trip.tenant, trip=trip, passenger=passenger, seat_label=labels[index],
                status=reservation_status, amount_xof=price, payment_method=method,
                payment_ref=f"TX-{uuid.uuid4().hex[:10].upper()}" if method in ("wave", "orange_money") else "",
                sales_channel="onboard" if method == "onboard_cash" else random.choice(["counter", "online"]),
                boarded_at=trip.actual_departure_at if reservation_status == Reservation.Status.BOARDED else None,
                boarding_method="qr_scan" if reservation_status == Reservation.Status.BOARDED else "",
                refusal_reason="Billet illisible et pièce d'identité absente"
                if reservation_status == Reservation.Status.REFUSED else "",
            )
            reservation.qr_code_jwt = sign_ticket_jwt(reservation)
            reservation.save(update_fields=["qr_code_jwt"])
            made += 1

        boarded = trip.reservations.filter(status=Reservation.Status.BOARDED).count()
        Trip.objects.filter(pk=trip.pk).update(booked_seats=boarded)
        return made

    def _seed_control_session(self, trip, controller, status):
        if status not in (Trip.Status.COMPLETED, Trip.Status.BOARDING, Trip.Status.IN_TRANSIT):
            return
        boarded = trip.reservations.filter(status=Reservation.Status.BOARDED).count()
        no_show = trip.reservations.filter(status=Reservation.Status.NO_SHOW).count()

        if status == Trip.Status.COMPLETED:
            opened_at = trip.actual_departure_at or trip.scheduled_at
            closed_at = (trip.actual_arrival_at or trip.scheduled_at) + timedelta(minutes=random.randint(1, 10))
            sync_state, summary = ControlSession.SyncState.SYNCED, {
                "boarded": boarded, "no_show": no_show, "cash_xof": boarded * 500,
            }
        else:
            opened_at = (trip.actual_departure_at or trip.scheduled_at) - timedelta(minutes=30)
            closed_at, sync_state, summary = None, ControlSession.SyncState.DRAFT, None

        session, _ = ControlSession.objects.get_or_create(
            trip=trip, controller=controller,
            defaults={
                "tenant": trip.tenant,
                "device_id": f"device-{controller.matricule}-{random.randint(1000, 9999)}",
                "device_info": {"model": "Samsung Galaxy A54", "os": "Android 14", "app": "1.0.0"},
                "opened_at": opened_at, "closed_at": closed_at,
                "sync_state": sync_state, "close_summary": summary,
            },
        )
        if closed_at is not None:
            self._seed_control_events(session)

    def _seed_control_events(self, session):
        if session.events.exists():
            return
        trip = session.trip
        boarded = list(trip.reservations.filter(status=Reservation.Status.BOARDED)[:15])
        base = session.opened_at

        for offset, reservation in enumerate(boarded):
            ControlEvent.objects.create(
                tenant=trip.tenant, session=session, client_uuid=uuid.uuid4(),
                event_type="reservation_board", target_type="reservation", target_id=reservation.id,
                payload={"reservation_id": str(reservation.id), "boarding_method": "qr_scan"},
                status=ControlEvent.Status.PROCESSED,
                created_at_local=base + timedelta(minutes=offset), processed_at=session.closed_at,
            )

        for index in range(2):
            event = ControlEvent.objects.create(
                tenant=trip.tenant, session=session, client_uuid=uuid.uuid4(),
                event_type="anomaly_create", payload={"title": "Anomalie signalée à bord"},
                status=ControlEvent.Status.PROCESSED,
                created_at_local=base + timedelta(minutes=20 + index), processed_at=session.closed_at,
            )
            anomaly_type = random.choice([Anomaly.Type.DUPLICATE_SCAN, Anomaly.Type.SEAT_CONFLICT])
            Anomaly.objects.create(
                tenant=trip.tenant, session=session, event=event, type=anomaly_type,
                severity=random.choice([Anomaly.Severity.LOW, Anomaly.Severity.MODERATE]),
                status=Anomaly.Status.RESOLVED,
                title=f"{anomaly_type.label} — {trip.internal_id}",
                description="Détectée pendant le contrôle, régularisée avec le passager.",
                target_type="reservation", resolved_at=session.closed_at,
                resolution_notes="Régularisé à bord.", resolved_by=session.controller.user,
            )

        price = trip.reservations.first().amount_xof if trip.reservations.exists() else 5000
        for index in range(2):
            ControlEvent.objects.create(
                tenant=trip.tenant, session=session, client_uuid=uuid.uuid4(),
                event_type="onboard_sale", payload={"amount_xof": price, "seat_label": "—"},
                status=ControlEvent.Status.PROCESSED,
                created_at_local=base + timedelta(minutes=25 + index), processed_at=session.closed_at,
            )
            CashEntry.objects.create(
                tenant=trip.tenant, session=session, amount_xof=price,
                reason=CashEntry.Reason.ONBOARD_SALE, collected_by=session.controller,
            )

        ControlEvent.objects.create(
            tenant=trip.tenant, session=session, client_uuid=uuid.uuid4(),
            event_type="activity_transition", payload={"to_status": Trip.Status.IN_TRANSIT},
            status=ControlEvent.Status.PROCESSED,
            created_at_local=base + timedelta(minutes=35), processed_at=session.closed_at,
        )

        for _ in range(2):
            CashEntry.objects.create(
                tenant=trip.tenant, session=session, amount_xof=random.choice([1000, 1500, 2000]),
                reason=CashEntry.Reason.LUGGAGE_EXCESS, collected_by=session.controller,
            )

    def _seed_incident(self, tenant, controllers):
        trip = Trip.objects.filter(tenant=tenant, status=Trip.Status.COMPLETED).order_by("internal_id").first()
        if trip is None or not controllers:
            return
        if tenant.slug == "sahel-express":
            spec = (Incident.Type.BREAKDOWN, Incident.Severity.MODERATE,
                    "Panne moteur à hauteur de Tambacounda",
                    "Surchauffe moteur signalée par le chauffeur. Arrêt 90 min, "
                    "réparation d'appoint puis reprise du trajet vers Kayes.")
        else:
            spec = (Incident.Type.BEHAVIOR, Incident.Severity.LOW,
                    "Passager en état d'ivresse",
                    "Passager perturbateur au départ de Baux Maraîchers. "
                    "Débarqué à Thiès avec l'accord du dispatcher.")
        incident_type, severity, title, description = spec
        Incident.objects.get_or_create(
            tenant=tenant, trip=trip, title=title,
            defaults={
                "session": ControlSession.objects.filter(trip=trip).first(),
                "reporter": controllers[0].user, "type": incident_type, "severity": severity,
                "description": description, "status": Incident.Status.RESOLVED,
                "dispatcher_notified": True,
                "dispatcher_notified_at": trip.actual_departure_at,
                "resolved_at": trip.actual_arrival_at,
            },
        )

    # ─── 6. Colis ───

    def seed_colis(self):
        if not self.require(Place.objects.filter(tenant__isnull=True), "Places"):
            return
        orders = parcels = tasks = proofs = 0
        counter = 0

        for tenant in self.tenants():
            prefix = self.prefix_for(tenant)
            specs = self._colis_specs(tenant)
            for index, (status, trip, pickup, dropoff, amount) in enumerate(specs):
                internal_id = f"CMD-{prefix}-{timezone.now():%Y%m%d}-{index:02d}"
                order, was_created = Order.objects.get_or_create(
                    tenant=tenant, internal_id=internal_id,
                    defaults={
                        "customer_name": f"{random.choice(PASSENGER_FIRST)} {random.choice(PASSENGER_LAST)}",
                        "customer_phone": phone(), "pickup_place": pickup, "dropoff_place": dropoff,
                        "trip": trip, "status": status, "total_amount_xof": amount,
                        "priority": Order.Priority.STANDARD,
                        "payment_status": Order.PaymentStatus.PAID
                        if status == Order.Status.DELIVERED else Order.PaymentStatus.PENDING,
                        "pickup_window_start": timezone.now() - timedelta(days=2),
                        "pickup_window_end": timezone.now() - timedelta(days=2) + timedelta(hours=4),
                        "delivery_window_start": timezone.now() - timedelta(days=1),
                        "delivery_window_end": timezone.now() - timedelta(days=1) + timedelta(hours=6),
                        "instructions": "Appeler le destinataire 30 min avant la livraison.",
                    },
                )
                orders += was_created

                # rng dédié : le nombre de colis fixe les tracking_number suivants.
                for _ in range(self.rng(f"parcels-{tenant.slug}-{index}").randint(1, 3)):
                    counter += 1
                    _, made = Parcel.objects.get_or_create(
                        tracking_number=f"TP-{prefix}-{counter:05d}",
                        defaults={
                            "tenant": tenant, "order": order,
                            "description": random.choice([
                                "Carton de documents", "Sac de tissus", "Pièces détachées",
                                "Colis alimentaire scellé", "Matériel informatique",
                            ]),
                            "weight_kg": Decimal(str(round(random.uniform(1, 25), 2))),
                            "category": Parcel.Category.STANDARD,
                            "declared_value_xof": random.randint(5000, 150000),
                            "status": self._parcel_status(status),
                        },
                    )
                    parcels += made

                task, made = DeliveryTask.objects.get_or_create(
                    tenant=tenant, order=order, type=DeliveryTask.TaskType.DELIVERY,
                    defaults={
                        "place": dropoff, "status": self._task_status(status),
                        "driver": Driver.objects.filter(tenant=tenant).first(),
                        "vehicle": Vehicle.objects.filter(tenant=tenant).first(),
                        "sequence_order": index + 1,
                        "estimated_arrival": timezone.now() - timedelta(days=1),
                        "actual_arrival": timezone.now() - timedelta(days=1)
                        if status == Order.Status.DELIVERED else None,
                        "completed_at": timezone.now() - timedelta(days=1)
                        if status == Order.Status.DELIVERED else None,
                    },
                )
                tasks += made

                if status == Order.Status.DELIVERED:
                    _, made = ProofOfDelivery.objects.get_or_create(
                        tenant=tenant, delivery_task=task, type=ProofOfDelivery.PodType.SIGNATURE,
                        defaults={
                            "signature_url": f"https://demo.toupac.local/pod/{uuid.uuid4()}.jpg",
                            "recipient_name": f"{random.choice(PASSENGER_FIRST)} {random.choice(PASSENGER_LAST)}",
                            "recipient_phone": phone(),
                            "notes": "Remis en main propre.",
                            "gps_location": jitter(dropoff.location.x, dropoff.location.y, 0.002),
                        },
                    )
                    proofs += made

        self.step("Colis", f"{orders} commandes, {parcels} colis, {tasks} tâches, "
                           f"{proofs} preuves (nouvelles)")

    def _colis_specs(self, tenant):
        """(status, trip, pickup, dropoff, montant) des commandes à créer."""
        if tenant.slug == "sahel-express":
            dakar, bamako = self.place("Gare Routière Pompiers"), self.place("Gare Routière Sogoniko")
            kaolack = self.place("Gare Routière Kaolack")
            completed = Trip.objects.filter(tenant=tenant, status=Trip.Status.COMPLETED,
                                            route__code="DKR-BKO").first()
            in_transit = Trip.objects.filter(tenant=tenant, status=Trip.Status.IN_TRANSIT).first()
            upcoming = Trip.objects.filter(tenant=tenant, status=Trip.Status.SCHEDULED).first()
            return [
                (Order.Status.DELIVERED, completed, dakar, bamako, 12000),
                (Order.Status.DELIVERED, completed, dakar, bamako, 8500),
                (Order.Status.IN_TRANSIT, in_transit, dakar, bamako, 15000),
                (Order.Status.CONFIRMED, upcoming, dakar, bamako, 9000),
                # Order n'a pas de statut « created » (c'est un statut de Parcel) :
                # le colis sans bus part donc en brouillon.
                (Order.Status.DRAFT, None, dakar, kaolack, 3500),
            ]
        dakar = self.place("Gare Routière Baux Maraîchers")
        thies, kaolack = self.place("Gare Routière Thiès"), self.place("Gare Routière Kaolack")
        return [
            (Order.Status.DELIVERED, None, dakar, thies, 2500),
            (Order.Status.DELIVERED, None, dakar, kaolack, 4000),
            (Order.Status.IN_TRANSIT, None, dakar, thies, 3000),
        ]

    @staticmethod
    def _parcel_status(order_status):
        return {
            Order.Status.DELIVERED: Parcel.Status.DELIVERED,
            Order.Status.IN_TRANSIT: Parcel.Status.IN_TRANSIT,
            Order.Status.CONFIRMED: Parcel.Status.CREATED,
            Order.Status.DRAFT: Parcel.Status.CREATED,
        }.get(order_status, Parcel.Status.CREATED)

    @staticmethod
    def _task_status(order_status):
        return {
            Order.Status.DELIVERED: DeliveryTask.Status.COMPLETED,
            Order.Status.IN_TRANSIT: DeliveryTask.Status.EN_ROUTE,
            Order.Status.CONFIRMED: DeliveryTask.Status.ASSIGNED,
            Order.Status.DRAFT: DeliveryTask.Status.PENDING,
        }.get(order_status, DeliveryTask.Status.PENDING)

    # ─── 7. Facturation ───

    def seed_billing(self):
        if not self.require(Route.objects.all(), "Routes"):
            return
        lists = rules = invoices = payments = 0

        for tenant in self.tenants():
            voyage_list, made = PriceList.objects.get_or_create(
                tenant=tenant, name=f"Grille Voyage {'2026' if tenant.slug == 'sahel-express' else 'Dem Dikk'}",
                defaults={"type": PriceList.Type.VOYAGE, "currency": "XOF", "is_active": True},
            )
            lists += made
            for code, _departure, _days, price in SCHEDULES[tenant.slug]:
                route = Route.objects.filter(tenant=tenant, code=code).first()
                if route is None:
                    continue
                _, made = PriceRule.objects.get_or_create(
                    tenant=tenant, price_list=voyage_list, route=route,
                    calculation_method=PriceRule.CalculationMethod.FIXED,
                    defaults={"base_amount_xof": price},
                )
                rules += made

            if tenant.slug == "sahel-express":
                colis_list, made = PriceList.objects.get_or_create(
                    tenant=tenant, name="Grille Colis 2026",
                    defaults={"type": PriceList.Type.COLIS, "currency": "XOF", "is_active": True},
                )
                lists += made
                _, made = PriceRule.objects.get_or_create(
                    tenant=tenant, price_list=colis_list, route=None,
                    calculation_method=PriceRule.CalculationMethod.FIXED,
                    defaults={"base_amount_xof": 2000},
                )
                rules += made
                _, made = PriceRule.objects.get_or_create(
                    tenant=tenant, price_list=colis_list, route=None,
                    calculation_method=PriceRule.CalculationMethod.PER_KG,
                    defaults={"base_amount_xof": 500, "rate_per_unit": Decimal("250.00"),
                              "min_amount_xof": 1000, "max_amount_xof": 20000},
                )
                rules += made

            invoices += self._seed_invoices(tenant)
            payments += self._seed_payments(tenant)

        self.step("Facturation", f"{lists} grilles, {rules} règles, {invoices} factures, "
                                 f"{payments} paiements (nouveaux)")

    def _seed_invoices(self, tenant):
        wanted = 3 if tenant.slug == "sahel-express" else 2
        made = 0
        reservations = Reservation.objects.filter(
            tenant=tenant, trip__status=Trip.Status.COMPLETED, status=Reservation.Status.BOARDED,
        ).select_related("passenger", "trip__route").order_by("created_at")[:wanted]

        for reservation in reservations:
            # Clé fonctionnelle : InvoiceGenerator crée sans dédupliquer.
            if InvoiceLine.objects.filter(reference_type="reservation", reference_id=reservation.id).exists():
                continue
            InvoiceGenerator.from_reservation(reservation)
            made += 1

        if tenant.slug == "sahel-express":
            order = Order.objects.filter(tenant=tenant, status=Order.Status.DELIVERED).first()
            if order and not InvoiceLine.objects.filter(reference_type="order", reference_id=order.id).exists():
                InvoiceGenerator.from_order(order)
                made += 1
        return made

    def _seed_payments(self, tenant):
        prefix = self.prefix_for(tenant)
        invoices = list(Invoice.objects.filter(tenant=tenant).order_by("invoice_number"))
        if tenant.slug == "sahel-express":
            specs = [
                (Payment.Provider.WAVE, Payment.Status.SUCCESS, ""),
                (Payment.Provider.ORANGE_MONEY, Payment.Status.SUCCESS, ""),
                (Payment.Provider.CASH, Payment.Status.SUCCESS, ""),
                (Payment.Provider.WAVE, Payment.Status.FAILED, "Insufficient funds"),
            ]
        else:
            specs = [
                (Payment.Provider.WAVE, Payment.Status.SUCCESS, ""),
                (Payment.Provider.ORANGE_MONEY, Payment.Status.SUCCESS, ""),
                (Payment.Provider.WAVE, Payment.Status.PENDING, ""),
            ]

        made = 0
        for index, (provider, status, failure) in enumerate(specs):
            invoice = invoices[index] if index < len(invoices) else None
            _, was_created = Payment.objects.get_or_create(
                tenant=tenant, provider_tx_id=f"TX-{prefix}-{index:04d}",
                defaults={
                    "invoice": invoice, "provider": provider,
                    "amount_xof": invoice.total_xof if invoice else 5000,
                    "status": status, "failure_reason": failure,
                    "completed_at": timezone.now() - timedelta(days=1)
                    if status == Payment.Status.SUCCESS else None,
                    "provider_response": {"demo": True},
                },
            )
            made += was_created
        return made

    # ─── 8. Tracking ───

    def seed_tracking(self):
        if not self.require(Vehicle.objects.all(), "Véhicules"):
            return
        positions = geofences = links = 0
        now = timezone.now()

        for tenant in self.tenants():
            home = self.place(HOME_PLACE[tenant.slug])
            in_transit = Trip.objects.filter(tenant=tenant, status=Trip.Status.IN_TRANSIT).first()

            if in_transit and in_transit.vehicle and not Position.objects.filter(vehicle=in_transit.vehicle).exists():
                # Polyligne Dakar → Kaolack sur les 2 dernières heures.
                start, end = (14.6937, -17.4441), (14.1520, -16.0726)
                for step in range(20):
                    ratio = step / 19
                    lat = start[0] + (end[0] - start[0]) * ratio
                    lon = start[1] + (end[1] - start[1]) * ratio
                    Position.objects.create(
                        tenant=tenant, vehicle=in_transit.vehicle, driver=in_transit.driver,
                        location=jitter(lon, lat), speed_kmh=Decimal(str(random.randint(60, 90))),
                        heading=Decimal("95.0"), accuracy_m=random.randint(4, 12),
                        source=Position.Source.DRIVER_APP,
                        recorded_at=now - timedelta(minutes=(19 - step) * 6),
                    )
                    positions += 1

            for vehicle in Vehicle.objects.filter(tenant=tenant):
                if Position.objects.filter(vehicle=vehicle).exists():
                    continue
                for step in range(random.randint(2, 3)):
                    Position.objects.create(
                        tenant=tenant, vehicle=vehicle,
                        location=jitter(home.location.x, home.location.y, 0.002),
                        speed_kmh=Decimal("0.0"), accuracy_m=random.randint(4, 10),
                        source=Position.Source.TRACCAR,
                        recorded_at=now - timedelta(minutes=step * 15),
                    )
                    positions += 1

            hub_name = "Gare Routière Kaolack" if tenant.slug == "sahel-express" else "Gare Routière Thiès"
            for name, fence_type, place_name in [
                (f"Dépôt {home.city}", Geofence.FenceType.DEPOT, HOME_PLACE[tenant.slug]),
                (f"Hub {self.place(hub_name).city}", Geofence.FenceType.HUB, hub_name),
            ]:
                place = self.place(place_name)
                _, made = Geofence.objects.get_or_create(
                    tenant=tenant, name=name,
                    defaults={"type": fence_type, "is_active": True,
                              "boundary": octagon(place.location.x, place.location.y)},
                )
                geofences += made

            order = Order.objects.filter(tenant=tenant, status=Order.Status.DELIVERED).first()
            if order:
                _, made = TrackingLink.objects.get_or_create(
                    tenant=tenant, resource_type=TrackingLink.ResourceType.ORDER, resource_id=order.id,
                    defaults={"token": TrackingLink.generate_token(),
                              "expires_at": now + timedelta(days=30)},
                )
                links += made

        self.step("Tracking", f"{positions} positions, {geofences} géofences, {links} liens (nouveaux)")

    # ─── 9. Notifications ───

    def seed_notifications(self):
        templates = logs = 0
        for event_type, channel, subject, body in NOTIFICATION_TEMPLATES:
            _, made = NotificationTemplate.objects.get_or_create(
                tenant=None, event_type=event_type, channel=channel, language="fr",
                defaults={"subject": subject, "template_body": body, "is_active": True},
            )
            templates += made

        now = timezone.now()
        for tenant in self.tenants():
            prefix = self.prefix_for(tenant)
            passengers = list(Passenger.objects.filter(tenant=tenant)[:10])
            users = list(User.objects.filter(tenant=tenant))
            for index in range(10):
                event_type, channel, _subject, body = NOTIFICATION_TEMPLATES[index % len(NOTIFICATION_TEMPLATES)]
                if channel == "email":
                    recipient = users[index % len(users)].email if users else "demo@example.sn"
                else:
                    recipient = passengers[index % len(passengers)].phone if passengers else phone()
                status = [NotificationLog.Status.SENT, NotificationLog.Status.DELIVERED,
                          NotificationLog.Status.FAILED][index % 3]
                _, made = NotificationLog.objects.get_or_create(
                    tenant=tenant, provider_message_id=f"MSG-{prefix}-{index:03d}",
                    defaults={
                        "user": users[index % len(users)] if users else None,
                        "channel": channel, "recipient": recipient, "event_type": event_type,
                        "content": body, "status": status,
                        "provider": "console",
                        "failure_reason": "Numéro injoignable" if status == NotificationLog.Status.FAILED else "",
                        "sent_at": now - timedelta(hours=index),
                        "delivered_at": now - timedelta(hours=index) + timedelta(seconds=30)
                        if status == NotificationLog.Status.DELIVERED else None,
                    },
                )
                logs += made

        self.step("Notifications", f"{templates} templates, {logs} logs (nouveaux)")

    # ─── Récapitulatif ───

    def print_summary(self):
        width = 78
        line = "─" * width
        out = self.stdout
        out.write("")
        out.write(f"┌{line}┐")
        out.write(f"│ {'TOUPAC — JEU DE DONNÉES DE DÉMONSTRATION':<{width - 2}} │")
        out.write(f"├{line}┤")

        for tenant in self.tenants():
            stats = (
                f"{User.objects.filter(tenant=tenant).count()} users · "
                f"{Vehicle.objects.filter(tenant=tenant).count()} véhicules · "
                f"{Route.objects.filter(tenant=tenant).count()} routes · "
                f"{Trip.objects.filter(tenant=tenant).count()} voyages · "
                f"{Reservation.objects.filter(tenant=tenant).count()} réservations"
            )
            extra = (
                f"{Order.objects.filter(tenant=tenant).count()} commandes · "
                f"{Invoice.objects.filter(tenant=tenant).count()} factures · "
                f"{Payment.objects.filter(tenant=tenant).count()} paiements · "
                f"{Position.objects.filter(tenant=tenant).count()} positions"
            )
            out.write(f"│ {tenant.name:<{width - 2}} │")
            out.write(f"│   {stats:<{width - 4}} │")
            out.write(f"│   {extra:<{width - 4}} │")

        out.write(f"├{line}┤")
        out.write(f"│ {'COMPTES DE CONNEXION — mot de passe : ' + DEMO_PASSWORD:<{width - 2}} │")
        for tenant in self.tenants():
            for user in User.objects.filter(tenant=tenant).order_by("role", "email"):
                entry = f"{user.email:<32} {user.role:<12} {'(admin Django)' if user.is_staff else ''}"
                out.write(f"│   {entry:<{width - 4}} │")

        out.write(f"├{line}┤")
        out.write(f"│ {'IDS UTILES POUR TESTER':<{width - 2}} │")
        for label, value in self.useful_ids().items():
            out.write(f"│   {f'{label}: {value}':<{width - 4}} │")

        out.write(f"├{line}┤")
        out.write(f"│   {'Admin   : http://localhost:8000/admin/':<{width - 4}} │")
        out.write(f"│   {'Swagger : http://localhost:8000/api/docs/':<{width - 4}} │")
        out.write(f"└{line}┘")

    def useful_ids(self):
        ids = {}
        trip = Trip.objects.filter(status=Trip.Status.IN_TRANSIT).order_by("internal_id").first()
        if trip:
            ids["trip_id (in_transit)"] = str(trip.id)
            session = ControlSession.objects.filter(trip=trip, closed_at__isnull=True).first()
            if session:
                ids["session_id (active)"] = str(session.id)
            reservation = trip.reservations.exclude(qr_code_jwt="").first()
            if reservation:
                ids["reservation_id (QR)"] = str(reservation.id)
        order = Order.objects.filter(status=Order.Status.DELIVERED).order_by("internal_id").first()
        if order:
            ids["order_id (tracking)"] = str(order.id)
        link = TrackingLink.objects.order_by("created_at").first()
        if link:
            ids["tracking token"] = link.token
        return ids or {"—": "aucune donnée (lancez le seed complet)"}
