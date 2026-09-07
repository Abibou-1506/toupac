"""
TOUPAC Notifications — Politique de réessai par canal (N-09).

Tous les canaux ne se valent pas face à l'échec :

- **Push et e-mail** sont gratuits et transitoires : un serveur momentanément
  injoignable justifie de réessayer, avec un délai qui double à chaque fois pour
  ne pas s'acharner sur un service en difficulté.
- **SMS et WhatsApp** sont facturés à l'envoi. Réessayer un code de connexion
  trois fois, c'est le payer trois fois — et l'utilisateur en aura de toute
  façon redemandé un nouveau avant la troisième tentative.
- **In-app** est une écriture en base : si elle échoue, la base est indisponible
  ou le code est fautif. Réessayer masquerait un incident au lieu de le révéler.

Déclaratif plutôt que dispersé dans la tâche Celery : la politique se lit d'un
coup d'œil, et un canal ajouté sans entrée ici retombe sur « aucun réessai »,
qui est le défaut prudent.
"""
from dataclasses import dataclass

from .channels import Channel


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int
    base_delay_seconds: int

    def countdown_for(self, retry_number: int) -> int:
        """Délai avant la tentative suivante — exponentiel : 60 s, 120 s, 240 s."""
        return self.base_delay_seconds * (2 ** retry_number)


#: Aucun réessai : le défaut pour tout canal non déclaré.
NO_RETRY = RetryPolicy(max_retries=0, base_delay_seconds=0)

RETRY_POLICIES: dict[Channel, RetryPolicy] = {
    Channel.PUSH: RetryPolicy(max_retries=3, base_delay_seconds=60),
    Channel.EMAIL: RetryPolicy(max_retries=3, base_delay_seconds=60),
    Channel.SMS: NO_RETRY,
    Channel.WHATSAPP: NO_RETRY,
    Channel.IN_APP: NO_RETRY,
}


def get_retry_policy(channel) -> RetryPolicy:
    """Politique du canal. Un canal inconnu ne réessaie pas."""
    try:
        resolved = Channel(channel)
    except ValueError:
        return NO_RETRY
    return RETRY_POLICIES.get(resolved, NO_RETRY)
