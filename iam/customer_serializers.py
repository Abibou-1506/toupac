"""
TOUPAC IAM — Représentations destinées au client TOUPAC.

Ces serializers sont volontairement **explicites et fermés** : chaque champ
exposé est écrit à la main, aucun `fields = "__all__"`. Les modèles métier
portent des colonnes d'exploitation — qui a créé la réservation, qui a fait
embarquer, le motif d'un refus, la réponse brute du prestataire de paiement —
qui appartiennent à la compagnie, pas au voyageur. Une liste blanche rend
impossible qu'un champ ajouté plus tard fuite par inadvertance.

Chaque élément porte `tenant_slug` et `tenant_name` : ces listes sont
transverses aux compagnies, et un billet sans son transporteur serait
inexploitable pour le client.
"""
from rest_framework import serializers


class MyReservationSerializer(serializers.Serializer):
    """Une réservation vue par le voyageur."""

    id = serializers.UUIDField(read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    trip_route_name = serializers.CharField(source="trip.route.name", read_only=True)
    trip_route_code = serializers.CharField(source="trip.route.code", read_only=True)
    trip_departure_date = serializers.DateField(source="trip.departure_date", read_only=True)
    trip_scheduled_at = serializers.DateTimeField(source="trip.scheduled_at", read_only=True)
    seat_label = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    amount_xof = serializers.IntegerField(read_only=True)
    passenger_full_name = serializers.CharField(source="passenger.full_name", read_only=True)
    # Jamais exposés : created_by, boarded_by, boarding_method,
    # special_case_reason, refusal_reason (motifs d'exploitation), et
    # qr_code_jwt — le jeton d'embarquement vaut le billet lui-même.


class MyOrderSerializer(serializers.Serializer):
    """Une commande de colis vue par son commanditaire."""

    id = serializers.UUIDField(read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    internal_id = serializers.CharField(read_only=True)
    pickup_place_name = serializers.CharField(source="pickup_place.name", read_only=True)
    dropoff_place_name = serializers.CharField(source="dropoff_place.name", read_only=True)
    status = serializers.CharField(read_only=True)
    payment_status = serializers.CharField(read_only=True)
    total_amount_xof = serializers.IntegerField(read_only=True)
    priority = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    # Jamais exposés : created_by, metadata, instructions — ces dernières sont
    # des consignes d'exploitation adressées au livreur, pas au client.


class MyPaymentSerializer(serializers.Serializer):
    """Un paiement vu par celui qui l'a réglé."""

    id = serializers.UUIDField(read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    provider = serializers.CharField(read_only=True)
    amount_xof = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    initiated_at = serializers.DateTimeField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True)
    # Un paiement isolé ne dit rien : le rattacher à ce qu'il règle est ce qui
    # le rend lisible dans un historique.
    context_type = serializers.SerializerMethodField()
    context_reference = serializers.SerializerMethodField()
    # Jamais exposés : provider_tx_id et provider_response (identifiants et
    # charge utile du prestataire, réservés au rapprochement comptable),
    # failure_reason (message technique, pas un motif présentable).

    def get_context_type(self, obj):
        if obj.order_id:
            return "order"
        if obj.invoice_id:
            return "invoice"
        if obj.reservation_id:
            return "reservation"
        return None

    def get_context_reference(self, obj):
        if obj.order_id:
            return obj.order.internal_id
        if obj.invoice_id:
            return obj.invoice.invoice_number
        if obj.reservation_id:
            return obj.reservation.seat_label
        return None


class MyNotificationSerializer(serializers.Serializer):
    """
    Un item du centre d'alertes, vu par son destinataire.

    `category` et `requires_ack` ne sont pas stockés sur la ligne : ils
    appartiennent à l'événement, que le catalogue décrit. Les dériver ici évite
    de dupliquer en base une information qui changerait alors sans que les
    lignes déjà écrites en tiennent compte. Le coût est nul — le catalogue est
    un dictionnaire en mémoire, jamais une requête.

    Le corps est rendu intégralement. Les masques de confidentialité (N-05) ne
    s'appliquent qu'au rendu poussé, où l'aperçu s'affiche sur un écran
    verrouillé ; ici le destinataire s'est authentifié pour lire ce qui lui
    appartient.
    """

    id = serializers.UUIDField(read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    event_code = serializers.CharField(read_only=True)
    category = serializers.SerializerMethodField()
    priority = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)
    action_url = serializers.CharField(read_only=True)
    read_at = serializers.DateTimeField(read_only=True)
    acked_at = serializers.DateTimeField(read_only=True)
    requires_ack = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    # Jamais exposés : trigger_scope et trigger_role (par quelle diffusion
    # l'alerte est arrivée — audit interne, sans intérêt pour le destinataire),
    # idempotency_key (mécanique du service) et expires_at (échéance de purge,
    # qui ne décrit pas la notification mais sa rétention).

    # Les annotations ne sont pas décoratives : sans elles, drf-spectacular
    # publie `requires_ack` en chaîne de caractères, et un client généré depuis
    # le schéma testerait la vérité d'une chaîne toujours vraie.
    def get_category(self, obj) -> str:
        return self._event_attribute(obj, "category", "")

    def get_requires_ack(self, obj) -> bool:
        return self._event_attribute(obj, "requires_ack", False)

    @staticmethod
    def _event_attribute(obj, name, default):
        """
        Attribut de l'événement, ou un défaut si le catalogue l'ignore.

        Un code retiré du catalogue laisse derrière lui des lignes déjà écrites.
        Les faire échouer à la lecture rendrait tout le centre d'alertes
        inaccessible pour une seule ligne périmée.
        """
        from notifications import catalog

        try:
            return getattr(catalog.get_event(obj.event_code), name)
        except KeyError:
            return default
