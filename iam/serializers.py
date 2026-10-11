from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class ToupacTokenObtainSerializer(TokenObtainPairSerializer):
    """JWT custom : ajoute tenant_id et role dans le token."""
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["tenant_id"] = str(user.tenant_id) if user.tenant_id else None
        token["role"] = user.role
        token["name"] = user.full_name
        return token


class UserSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True, default=None)

    class Meta:
        model = User
        # `is_superuser` : exposé pour que le front conditionne les actions
        # réservées à TOUPAC (ex. suppression des notes RH chauffeur). Additif,
        # read-only — un ADMIN de compagnie ne pourrait pas se promouvoir via
        # ce payload. Résout dette V1.1 (DriverDetailPage).
        fields = [
            "id", "email", "first_name", "last_name", "phone", "role",
            "tenant_id", "tenant_name", "is_active", "is_superuser",
        ]
        read_only_fields = ["id", "email", "role", "tenant_id", "is_superuser"]


class UserMiniSerializer(serializers.ModelSerializer):
    """Projection compacte pour les pickers (ex. choix d'un user pour FK chauffeur).

    Pas de tenant_id : la liste est déjà filtrée côté vue par
    `request.tenant`, ré-exposer le tenant_id n'aide pas le client et
    alourdit le payload.
    """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "phone", "is_active"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()
