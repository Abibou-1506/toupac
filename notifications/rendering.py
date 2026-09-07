"""
TOUPAC Notifications — Rendu des gabarits, avec confidentialité par canal (N-05).

Un même événement ne se raconte pas pareil selon où il arrive. Le masque ne
supprime pas une information : il **diffère** sa lecture vers un canal où le
destinataire aura prouvé son identité. C'est ce qui permet à un billet
(`notif.ticket.issued.v1`) d'annoncer « votre billet est prêt » sur un écran
verrouillé tout en livrant le QR code réel dans l'application.

Le masque ne vaut donc que là où ce report a un sens :

- **Push** — un aperçu s'affiche sur un écran verrouillé, lisible par qui passe
  derrière. Les variables déclarées `confidentiality_masks` y deviennent ``***``,
  et le destinataire ouvre l'application pour voir le reste.
- **In-app, e-mail** — atteints après authentification, ou dans une boîte
  personnelle. Charge utile complète.
- **SMS, WhatsApp** — charge utile complète également, et c'est délibéré. Ces
  deux canaux sont réservés aux codes à usage unique (décision produit du
  2 septembre, vérifiée par `test_sms_and_whatsapp_are_reserved_to_otp_events`).
  Or `notif.auth.otp_signin.v1` déclare précisément `otp` comme variable
  sensible : la masquer ici enverrait « votre code est *** » et rendrait la
  connexion impossible. Il n'y a pas d'« ailleurs » où lire le code — ces canaux
  sont la livraison, pas l'aperçu.
"""
from django.template import Context, Template

from .channels import Channel

#: Seul canal produisant un aperçu non authentifié d'un contenu lisible ailleurs.
CHANNELS_MASKING_APPLIED = frozenset({Channel.PUSH})

#: Canaux recevant la charge utile complète — voir le module pour le pourquoi.
CHANNELS_FULL_PAYLOAD = frozenset(
    {Channel.IN_APP, Channel.EMAIL, Channel.SMS, Channel.WHATSAPP}
)

#: Remplacement des variables masquées. Volontairement visible : l'utilisateur
#: doit comprendre qu'une information existe et qu'elle est ailleurs.
MASK_PLACEHOLDER = "***"


def mask_context(context, event, channel):
    """Copie du contexte, variables sensibles masquées si le canal l'exige."""
    if Channel(channel) not in CHANNELS_MASKING_APPLIED:
        return context

    masked = dict(context)
    for variable in event.confidentiality_masks:
        if variable in masked:
            masked[variable] = MASK_PLACEHOLDER
    return masked


def render_for_channel(template, context, event, channel):
    """
    Rend `(title, body, action_url)` pour un canal.

    Lève `TemplateSyntaxError` si un gabarit est mal formé — l'appelant en fait
    une trace d'échec plutôt que de laisser remonter l'erreur. Attention :
    Django lève à la **construction** du gabarit, pas au rendu, et un `{{` non
    fermé n'est pas une erreur pour lui mais du texte littéral.
    """
    render_context = Context(mask_context(context, event, channel))

    def render(source):
        return Template(source).render(render_context) if source else ""

    return (
        render(template.title_template),
        render(template.template_body),
        render(template.action_url_template),
    )
