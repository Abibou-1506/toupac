"""
TOUPAC IAM — Fabrique de l'utilisateur anonyme de django-guardian.

guardian matérialise en base un utilisateur « AnonymousUser », recréé par un
signal `post_migrate` à chaque migration — y compris sur chaque base de test.
Sa fabrique par défaut ne renseigne que `USERNAME_FIELD`, laissant `role` à sa
valeur par défaut (`agent`) et `tenant` à NULL : exactement la combinaison que
la contrainte `user_tenant_matches_role` interdit, puisqu'un agent de guichet
n'existe qu'au sein d'une compagnie.

Sans cette fabrique, `migrate` échoue sur une base neuve dès que la contrainte
est posée. On lui donne donc le rôle `SERVICE_ACCOUNT`, seul rôle que la
doctrine laisse volontairement libre de tenant — et qui décrit correctement ce
qu'est cette ligne : un compte technique, non humain, qui ne se connecte jamais.
Bénéfice collatéral, il hérite des masquages déjà en place pour les comptes de
service (liste des utilisateurs et menus déroulants de l'admin).

Branchée par `GUARDIAN_GET_INIT_ANONYMOUS_USER` dans les settings.
"""


def get_anonymous_user_instance(User):
    """Instance non sauvegardée de l'utilisateur anonyme guardian."""
    from guardian.conf import settings as guardian_settings

    # guardian retrouve cette ligne par `{USERNAME_FIELD: ANONYMOUS_USER_NAME}` :
    # la valeur doit rester exactement celle qu'il attend.
    user = User(
        **{User.USERNAME_FIELD: guardian_settings.ANONYMOUS_USER_NAME},
        first_name="Anonymous", last_name="User",
        tenant=None, role=User.Role.SERVICE_ACCOUNT,
        is_active=False, is_staff=False, is_superuser=False,
    )
    user.set_unusable_password()
    return user
