"""TOUPAC Notifications — Catégories de préférences utilisateur (N-02).

Le service (Ticket B) lit `user.notification_preferences.get(category, True)` :
absence de clé = opt-in par défaut. Les catégories `otp`, `security` et
`critical_ops` sont TOUJOURS opt-in (charte N-01 : les messages de service
critiques sont séparés du marketing et ne se désabonnent pas).

Les constantes vivent ici plutôt que dans le catalogue pour que
`catalog.register()` puisse valider chaque catégorie à l'import — une faute de
frappe dans une déclaration d'événement casse au démarrage, pas au premier
envoi.
"""

CATEGORY_OTP = "otp"                        # AUTH-01, AUTH-02, COL-05
CATEGORY_SECURITY = "security"              # AUTH-03, SI-01
CATEGORY_CRITICAL_OPS = "critical_ops"      # TRJ-04, INC-01, INC-02, FIN-01, CTL-01, GPS-01, CMP-01
CATEGORY_TRIP_UPDATES = "trip_updates"      # TRJ-01/02/03, CMD-01/02/03, TKT-01
CATEGORY_PARCEL_UPDATES = "parcel_updates"  # COL-01..04, COL-06
CATEGORY_PAYMENTS = "payments"              # PAY-*
CATEGORY_DISPATCH = "dispatch"              # DSP-*
CATEGORY_FLEET = "fleet"                    # FLT-*, GPS-02
CATEGORY_WORKFLOW = "workflow"              # APR-*, STK-*, CRM-*, BI-*
CATEGORY_MARKETING = "marketing"            # MKT-*

#: Catégories jamais désactivables — filet de sécurité appliqué par le service.
NEVER_OPT_OUT = frozenset({CATEGORY_OTP, CATEGORY_SECURITY, CATEGORY_CRITICAL_OPS})

ALL_CATEGORIES = frozenset({
    CATEGORY_OTP, CATEGORY_SECURITY, CATEGORY_CRITICAL_OPS,
    CATEGORY_TRIP_UPDATES, CATEGORY_PARCEL_UPDATES, CATEGORY_PAYMENTS,
    CATEGORY_DISPATCH, CATEGORY_FLEET, CATEGORY_WORKFLOW, CATEGORY_MARKETING,
})
