"""
TOUPAC Notifications — Briques communes aux resolvers métier.

Trois familles de destinataires cohabitent dans le système, et confondre leurs
filtres est le mode de défaillance le plus probable d'un resolver : il rend une
liste vide, l'émission passe pour un « personne à prévenir » légitime, et rien
en base ne dit que c'était une erreur.

- **Personnel d'une compagnie** — filtré par `tenant`, par rôle, actif.
- **Client TOUPAC** — global, `tenant=None`. Le filtrer par `tenant` ne rend
  jamais rien : un client n'appartient à aucune compagnie (USR-1).
- **Admin SI de la plateforme** — `SUPERADMIN`, sans compagnie lui aussi.

D'où ces fonctions plutôt que des `User.objects.filter(...)` recopiés : la règle
de chaque famille est écrite une fois.
"""
from .base import ResolvedRecipient


def staff_with_roles(tenant, *roles):
    """
    Personnel actif d'une compagnie, pour un ou plusieurs rôles.

    Sans `tenant`, rien : diffuser à « tous les dispatchers » sans compagnie
    toucherait ceux de toutes les compagnies à la fois.
    """
    from iam.models import User

    if tenant is None or not roles:
        return []
    return list(
        User.objects.filter(tenant=tenant, role__in=roles, is_active=True)
        .order_by("email", "pk"),
    )


def platform_admins():
    """
    Admins SI TOUPAC — les `SUPERADMIN`, qui sont sans compagnie par contrainte.

    À ne pas confondre avec l'admin d'une compagnie (`ADMIN`) : la charte
    distingue « Admin SI » (AUTH-03, SI-01), qui est TOUPAC, de l'administrateur
    du client, qui ne doit rien savoir des incidents de la plateforme.
    """
    from iam.models import User

    return list(
        User.objects.filter(role=User.Role.SUPERADMIN, is_active=True)
        .order_by("email", "pk"),
    )


def client_by_id(user_id):
    """
    Un client TOUPAC par identifiant. Ni compagnie, ni rôle deviné.

    Le filtre `role=CLIENT` n'est pas de la ceinture et bretelles : sans lui, un
    identifiant de salarié passé par erreur dans le contexte enverrait à ce
    salarié une notification destinée à un client. C'est la même règle que
    « un identifiant ne doit pas servir de sonde entre populations », appliquée
    en amont plutôt qu'à la frontière HTTP.
    """
    from iam.models import User

    if not user_id:
        return None
    return User.objects.filter(pk=user_id, role=User.Role.CLIENT, is_active=True).first()


def staff_by_id(user_id, tenant, *roles):
    """
    Un membre du personnel désigné nommément, vérifié contre sa compagnie.

    Le contrôle du tenant est ce qui empêche un identifiant venu d'ailleurs de
    faire sortir une notification de sa compagnie.
    """
    from iam.models import User

    if not user_id or tenant is None:
        return None
    queryset = User.objects.filter(pk=user_id, tenant=tenant, is_active=True)
    if roles:
        queryset = queryset.filter(role__in=roles)
    return queryset.first()


def user_by_id(user_id):
    """
    N'importe quel compte actif, sans présumer de son rôle.

    Réservé à `auth.*` : la connexion par code sert aussi bien un client qu'un
    chauffeur, et le rôle n'est pas connu à l'avance. Partout ailleurs, préférer
    `client_by_id` ou `staff_by_id`, qui disent qui ils cherchent.
    """
    from iam.models import User

    if not user_id:
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


# ─── Mise en forme ───

def as_user_recipient(user):
    """Destinataire nommé — liste vide si le compte est absent."""
    if user is None:
        return []
    return [ResolvedRecipient(user=user, trigger_scope="user")]


def as_role_recipients(users, role):
    """Diffusion à un rôle : chaque compte reçoit sa propre notification."""
    return [
        ResolvedRecipient(user=user, trigger_scope="role", trigger_role=role)
        for user in users
    ]


def dedupe(*groups):
    """
    Concatène plusieurs sources en gardant la **première** occurrence d'un compte.

    Un chauffeur qui est aussi client de sa compagnie, un admin qui fait office
    de dispatcher : ces personnes apparaissent dans deux sources. La contrainte
    d'unicité de `Notification` absorberait le doublon côté centre d'alertes,
    mais les `NotificationLog` partiraient en double — donc les envois aussi,
    et sur les canaux facturés cela se paie deux fois.

    Garder la première n'est pas arbitraire : l'ordre des sources porte
    l'intention (le client d'abord, le personnel ensuite), et le premier
    `trigger_scope` rencontré est le plus spécifique.
    """
    seen = set()
    result = []
    for group in groups:
        for recipient in group:
            if recipient.user is None or recipient.user.pk in seen:
                continue
            seen.add(recipient.user.pk)
            result.append(recipient)
    return result
