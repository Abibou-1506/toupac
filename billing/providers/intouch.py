"""
TOUPAC Billing — Intégration Intouch (agrégateur mobile money Sénégal / Afrique de l'Ouest).

V1 : sandbox mocké — aucun appel réseau réel. Supporte Wave, Orange Money,
Free Money, MTN MoMo via un point d'entrée unique.

Docs API : https://developer.gointouchgroup.com
"""
import uuid

from django.conf import settings

from .base import PaymentProvider, PaymentResult


class IntouchProvider(PaymentProvider):
    """
    Intégration Intouch — agrégateur mobile money Sénégal / Afrique de l'Ouest.
    Supporte : Wave, Orange Money, Free Money, MTN MoMo.

    Docs API : https://developer.gointouchgroup.com

    Settings requis :
    - INTOUCH_LOGIN_AGENT
    - INTOUCH_PASSWORD_AGENT
    - INTOUCH_PARTNER_ID
    - INTOUCH_CALLBACK_URL
    """

    API_BASE = "https://api.gointouchgroup.com/v1"

    def __init__(self):
        self.login_agent = getattr(settings, "INTOUCH_LOGIN_AGENT", "SANDBOX_LOGIN")
        self.password_agent = getattr(settings, "INTOUCH_PASSWORD_AGENT", "SANDBOX_PASSWORD")
        self.partner_id = getattr(settings, "INTOUCH_PARTNER_ID", "SANDBOX_PARTNER")

    def initiate_payment(self, amount, currency, description, customer_phone, callback_url, metadata=None):
        """
        V1 SANDBOX : simule l'appel API.

        En production, faire un PUT vers {API_BASE}/cashout avec :
        {
            "login_agent": self.login_agent,
            "password_agent": self.password_agent,
            "partner_transaction_id": str(uuid4()),
            "amount": amount,
            "call_back_url": callback_url,
            "recipient_phone_number": customer_phone,
            "service_id": "WAVE" | "ORANGE_MONEY" | "FREE_MONEY",
        }
        Headers: {"Content-Type": "application/json"}
        """
        tx_id = f"SANDBOX-{uuid.uuid4().hex[:12]}"
        return PaymentResult(
            success=True,
            provider_tx_id=tx_id,
            redirect_url="",  # Intouch envoie un push USSD au client, pas de redirect
            raw_response={"sandbox": True, "tx_id": tx_id, "partner_id": self.partner_id},
        )

    def verify_callback(self, request_data, headers):
        """Vérifie que le partner_id dans le callback correspond."""
        return request_data.get("partner_id") == self.partner_id

    def get_transaction_status(self, provider_tx_id):
        """
        V1 SANDBOX : retourne toujours 'success'.
        En production, GET {API_BASE}/transactions/{provider_tx_id}/status
        """
        return "success"
