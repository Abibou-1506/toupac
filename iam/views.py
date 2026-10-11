import django_filters
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from .authentication import deny_token_until_expiry
from .models import User
from .serializers import ToupacTokenObtainSerializer, UserMiniSerializer, UserSerializer


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
    """
    POST /api/v1/auth/logout/ — Révoque le refresh token ET l'access courant (§4.19).

    Le refresh part dans la blacklist native de simplejwt ; l'access, que
    simplejwt ne sait pas révoquer, est ajouté au denylist Redis jusqu'à son
    expiration naturelle.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            # Après la blacklist du refresh : si celui-ci est invalide, on part
            # en 400 sans avoir révoqué l'access, et le client peut réessayer.
            deny_token_until_expiry(request.auth)
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


# ─── Users (listing par rôle, pour pickers front) ───

class UserListByRoleFilterSet(django_filters.FilterSet):
    role = django_filters.CharFilter(field_name="role")

    class Meta:
        model = User
        fields = ["role"]


@extend_schema(tags=["IAM"], responses=UserMiniSerializer(many=True))
class UserListByRoleView(generics.ListAPIView):
    """GET /api/v1/iam/users/?role=driver — liste users par rôle, tenant-scopé.

    Résout dette V1.1 Vague 4 : la page NewDriverPage avait un UUID
    text input pour le FK `user` ; expose maintenant un endpoint pour
    alimenter un picker. Pagination DRF standard (page_size=25).

    Le rôle CLIENT est exclu systématiquement du queryset — un CLIENT
    TOUPAC n'appartient à aucun tenant et sa liste n'a aucune raison
    opérationnelle de transiter par ce picker. L'exclusion est en dur
    plutôt qu'au filtre pour éviter qu'un `?role=client` ne devienne un
    canal de leak de la base passagers côté staff.

    Accès : staff authentifié (`IsAdminUser` = is_staff=True). Un
    chauffeur ou un contrôleur connecté à l'app mobile ne doit pas
    pouvoir énumérer les comptes de la compagnie.
    """
    serializer_class = UserMiniSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    filterset_class = UserListByRoleFilterSet

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if tenant is None:
            # Sans tenant résolu (superadmin TOUPAC sans X-Tenant-ID,
            # requête anonyme filtrée en amont) la liste est vide plutôt
            # que globale : un picker « choisir le user chauffeur » n'a
            # de sens qu'au sein d'une compagnie.
            return User.objects.none()
        return (
            User.objects
            .filter(tenant=tenant, is_active=True)
            .exclude(role=User.Role.CLIENT)
            .order_by("last_name", "first_name")
        )
