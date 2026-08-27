"""TOUPAC Billing — Interface abstraite des providers de paiement."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PaymentResult:
    success: bool
    provider_tx_id: str = ""
    redirect_url: str = ""  # URL de paiement où rediriger le client
    error_message: str = ""
    raw_response: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """Interface abstraite pour les providers de paiement (Wave, Orange Money, Intouch...)."""

    @abstractmethod
    def initiate_payment(self, amount, currency, description, customer_phone, callback_url, metadata=None):
        """Lance un paiement. Retourne un PaymentResult."""
        raise NotImplementedError

    @abstractmethod
    def verify_callback(self, request_data, headers):
        """Vérifie la signature du webhook callback."""
        raise NotImplementedError

    @abstractmethod
    def get_transaction_status(self, provider_tx_id):
        """Vérifie le statut d'une transaction. Retourne 'success'|'failed'|'pending'."""
        raise NotImplementedError
