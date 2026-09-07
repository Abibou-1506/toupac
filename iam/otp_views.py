"""
TOUPAC IAM — Connexion des clients par code à usage unique.

Le personnel des compagnies se connecte par e-mail et mot de passe
(`LoginView`). Un client TOUPAC, lui, n'a pas de mot de passe : il prouve qu'il
contrôle une adresse ou un numéro, et reçoit le même JWT que tout le monde. Rien
en aval ne distingue les deux voies — c'est `DenylistJWTAuthentication` qui
valide le jeton dans les deux cas.

Envoi synchrone, pas via Celery : l'utilisateur attend son code, l'écran suivant
lui demande de le saisir. Un envoi différé rendrait l'écran menteur.
"""
import logging

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from iam.models import User
from iam.otp import (
    OTP_TTL_SECONDS,
    create_challenge,
    mask_target,
    verify_challenge,
)
from notifications.services import NotificationService

logger = logging.getLogger("toupac.iam.otp")

_TAG = ["Auth"]

#: Code d'erreur interne → message rendu au client. Les codes restent stables,
#: les messages peuvent être retouchés sans casser d'intégration.
ERROR_MESSAGES = {
    "not_found": "Demande inconnue ou expirée. Redemandez un code.",
    "expired": "Code expiré. Redemandez un code.",
    "too_many_attempts": "Trop de tentatives. Redemandez un code.",
    "wrong_code": "Code incorrect.",
}


class _OTPRequestThrottle(AnonRateThrottle):
    """Chaque demande coûte un SMS : le plafond protège la facture autant que le compte."""

    scope = "auth_otp_request"


class _OTPVerifyThrottle(AnonRateThrottle):
    scope = "auth_otp_verify"


class OTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)


class OTPRequestResponseSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    channel = serializers.CharField()
    target_masked = serializers.CharField()
    expires_in_seconds = serializers.IntegerField()


class OTPVerifySerializer(serializers.Serializer):
    challenge_id = serializers.CharField()
    code = serializers.CharField(max_length=10)


class OTPVerifyResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


@extend_schema(
    tags=_TAG,
    request=OTPRequestSerializer,
    responses=OTPRequestResponseSerializer,
    examples=[
        OpenApiExample("Par e-mail", value={"email": "fatou@example.sn"}, request_only=True),
        OpenApiExample("Par téléphone", value={"phone": "+221771234567"}, request_only=True),
    ],
)
class RequestOTPView(APIView):
    """
    POST /api/v1/auth/otp/request/ — demande un code de connexion.

    Le compte client est créé au passage s'il n'existe pas : côté produit, se
    connecter et s'inscrire sont le même geste pour un passager.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [_OTPRequestThrottle]

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = (serializer.validated_data.get("email") or "").strip().lower() or None
        phone = (serializer.validated_data.get("phone") or "").strip()

        if not email and not phone:
            return Response(
                {"detail": "Fournissez au moins un email ou un téléphone."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user, _ = User.get_or_create_client(email=email, phone=phone)
        except ValueError as exc:
            # L'identifiant appartient déjà à un compte qui n'est pas un client
            # (un agent, par exemple). On ne crée pas de client, et on ne dit
            # pas non plus à l'appelant à qui l'adresse appartient.
            logger.warning("Demande OTP refusée : %s", exc)
            return Response(
                {"detail": "Cet identifiant ne permet pas la connexion par code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # L'e-mail l'emporte quand les deux sont fournis, comme dans
        # `get_or_create_client` : une seule règle de priorité dans tout le
        # système. Pour recevoir par SMS, n'envoyer que `phone`.
        if email:
            channel, target_type, target = "email", "email", email
        else:
            channel, target_type, target = "sms", "phone", phone

        challenge_id, code = create_challenge(user.id, target_type, target)
        self._deliver(challenge_id, channel, target, code)

        return Response({
            "challenge_id": challenge_id,
            "channel": channel,
            "target_masked": mask_target(target_type, target),
            "expires_in_seconds": OTP_TTL_SECONDS,
        })

    @staticmethod
    def _deliver(challenge_id, channel, target, code):
        """
        Envoie le code, sans jamais faire échouer la demande.

        Un provider en panne ou un gabarit manquant ne doit pas renvoyer une
        erreur à l'appelant : le challenge existe déjà, et le détail de l'échec
        renseignerait un attaquant sur l'existence du compte. L'incident part
        dans les journaux serveur, où l'exploitation le voit.
        """
        try:
            NotificationService.send_notification(
                tenant=None,
                event_code="notif.auth.otp_signin.v1",
                channel=channel,
                recipient=target,
                # Noms imposés par le catalogue (`notif.auth.otp_signin.v1`),
                # pas choisis ici : les gabarits sont rendus avec ces variables.
                context_data={"otp": code, "expires_in_minutes": OTP_TTL_SECONDS // 60},
                language="fr",
            )
        except Exception:
            logger.exception("Échec d'envoi du code OTP (challenge %s)", challenge_id)


@extend_schema(
    tags=_TAG,
    request=OTPVerifySerializer,
    responses=OTPVerifyResponseSerializer,
)
class VerifyOTPView(APIView):
    """
    POST /api/v1/auth/otp/verify/ — échange un code valide contre un JWT.

    Le jeton émis est celui de tout le monde : mêmes claims, même durée, même
    révocation au logout.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [_OTPVerifyThrottle]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id, error = verify_challenge(
            serializer.validated_data["challenge_id"],
            serializer.validated_data["code"],
        )
        if error:
            return Response(
                {"detail": ERROR_MESSAGES.get(error, "Vérification refusée."), "code": error},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = User.objects.filter(id=user_id, is_active=True).first()
        if user is None:
            # Compte supprimé ou désactivé entre la demande et la vérification.
            return Response(
                {"detail": "Ce compte n'est plus accessible.", "code": "not_found"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        # Mêmes claims que `ToupacTokenObtainSerializer`, pour qu'un client OTP
        # et un membre du personnel produisent des jetons interchangeables en
        # aval (middleware tenant, permissions, journalisation).
        refresh["tenant_id"] = str(user.tenant_id) if user.tenant_id else None
        refresh["role"] = user.role
        refresh["name"] = user.full_name

        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})
