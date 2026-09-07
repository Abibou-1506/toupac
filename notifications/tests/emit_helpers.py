"""Helpers partagés par les tests d'émission.

Émettre demande un décor : un événement du catalogue, un gabarit par canal, un
resolver qui rend des destinataires. Ces fonctions le montent pour que chaque
test parle de ce qu'il vérifie.
"""
from notifications.models import NotificationTemplate
from notifications.resolvers.base import _RESOLVERS, ResolvedRecipient

#: Événement de référence des tests : trois canaux, dont in-app, et une variable
#: sensible — de quoi exercer le masquage et le rattachement des envois.
TICKET_EVENT = "notif.ticket.issued.v1"

#: Contexte conforme au catalogue pour `TICKET_EVENT`.
TICKET_CONTEXT = {
    "reference": "REF-001",
    "qr_payload": "SECRET-QR-PAYLOAD",
    "route_label": "Dakar → Bamako",
}


def ticket_context(**overrides):
    from django.utils import timezone

    context = {**TICKET_CONTEXT, "departure_at": timezone.now()}
    context.update(overrides)
    return context


def make_template(event_code, channel, tenant=None, language="fr", **overrides):
    """Gabarit système par défaut, exposant les variables utiles aux assertions."""
    payload = {
        "title_template": "Billet {{ reference }}",
        "template_body": "Votre billet {{ reference }} — QR : {{ qr_payload }}",
        "action_url_template": "/billets/{{ reference }}",
        "is_active": True,
    }
    payload.update(overrides)
    return NotificationTemplate.objects.create(
        tenant=tenant, event_code=event_code, channel=channel,
        language=language, **payload,
    )


def make_templates_for_all_channels(event_code=TICKET_EVENT, channels=None, **overrides):
    """Un gabarit par canal déclaré, pour que rien n'échoue faute de gabarit."""
    from notifications.catalog import get_event

    channels = channels or [c.value for c in get_event(event_code).default_channels]
    return [make_template(event_code, channel, **overrides) for channel in channels]


class temporary_resolver:  # utilisé comme gestionnaire de contexte, d'où le nom en minuscules
    """
    Enregistre un resolver le temps d'un test, puis le retire.

    Le registre est un état de module peuplé au démarrage : y laisser une entrée
    ferait échouer le test suivant qui enregistre la même clé, avec un message
    qui ne dirait pas d'où vient le conflit.
    """

    def __init__(self, key, func):
        self.key = key
        self.func = func

    def __enter__(self):
        self._previous = _RESOLVERS.get(self.key)
        _RESOLVERS[self.key] = self.func
        return self.func

    def __exit__(self, *exc_info):
        if self._previous is None:
            _RESOLVERS.pop(self.key, None)
        else:
            _RESOLVERS[self.key] = self._previous
        return False


def resolver_returning(*users):
    """Resolver qui rend ces comptes, chacun visé individuellement."""
    def _resolve(context, tenant):
        return [
            ResolvedRecipient(user=user, trigger_scope="user")
            for user in users
        ]
    return _resolve


def resolver_raising(exc):
    def _resolve(context, tenant):
        raise exc
    return _resolve


def resolver_returning_nothing(context, tenant):
    return []
