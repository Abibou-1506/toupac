from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from .serializers import ToupacTokenObtainSerializer, UserSerializer


@extend_schema(tags=["Auth"])
class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — JWT access + refresh."""
    serializer_class = ToupacTokenObtainSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth_login"


@extend_schema(tags=["Auth"])
class TokenRefreshView(BaseTokenRefreshView):
    """POST /api/v1/auth/refresh/ — rotation des tokens JWT (simplejwt)."""


@extend_schema(
    tags=["Auth"],
    request=inline_serializer("LogoutRequest", {"refresh": serializers.CharField(required=False)}),
    responses=inline_serializer("LogoutResponse", {"detail": serializers.CharField()}),
)
class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — Révoque le refresh token (denylist §4.19)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response({"detail": "Déconnexion réussie."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"detail": "Token invalide."}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Auth"], responses=UserSerializer)
class MeView(APIView):
    """GET /api/v1/auth/me/ — Profil de l'utilisateur connecté."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
