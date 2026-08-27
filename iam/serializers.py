from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, Tenant


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
        fields = ["id", "email", "first_name", "last_name", "phone", "role", "tenant_id", "tenant_name", "is_active"]
        read_only_fields = ["id", "email", "role", "tenant_id"]
