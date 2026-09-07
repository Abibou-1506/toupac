"""
TOUPAC Notifications — Service central d'émission (charte TOUPAC ONE).

`NotificationService.emit()` est le seul point d'entrée : le code métier déclare
qu'un événement a eu lieu, le service décide qui prévenir, par quels canaux et
avec quel contenu. Appel explicite plutôt que signal Django — le flux se lit de
haut en bas, se met au point pas à pas, et un `grep` sur `emit(` donne la liste
exhaustive des émetteurs.

Le service **ne propage jamais d'exception au code métier** une fois passée la
validation d'entrée. Un gabarit manquant, un resolver absent, un fournisseur en
panne : chacun laisse une trace dans `NotificationLog` et l'émission continue
pour les autres destinataires et canaux. Une notification perdue en silence est
un incident invisible ; une notification perdue avec sa raison est un ticket.

Deux exceptions font exception, précisément parce qu'elles signalent un défaut
de l'appelant et non de la livraison : un code d'événement inconnu (`KeyError`)
et un contexte non conforme au catalogue (`ValueError`).
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q

from . import catalog
from .channels import Channel
from .idempotency import already_emitted, compute_idempotency_key, mark_emitted
from .models import Notification, NotificationLog, NotificationTemplate
from .preferences import NEVER_OPT_OUT
from .rendering import render_for_channel
from .resolvers.base import KNOWN_UNIMPLEMENTED_RESOLVERS, get_resolver

logger = logging.getLogger("toupac.notifications")

#: In-app d'abord : c'est ce canal qui matérialise l'item du centre d'alertes,
#: auquel les envois des autres canaux se rattachent. Les déclarations du
#: catalogue ne le placent en tête que pour 4 événements sur 37 — on ne peut
#: donc pas se fier à leur ordre.
_CHANNEL_PRIORITY = {Channel.IN_APP: 0}


def _ordered_channels(channels):
    return sorted(channels, key=lambda channel: _CHANNEL_PRIORITY.get(channel, 1))


@dataclass(frozen=True)
class RecipientTarget:
    """
    Destinataire désigné en clair, sans passer par un resolver.

    Le cas d'usage est le code de connexion : au moment où on l'envoie, on ne
    connaît qu'une adresse ou un numéro, et le compte n'est pas encore la
    référence — c'est précisément ce que l'utilisateur est en train de prouver.
    """

    type: str  # "email" | "phone" | "user"
    value: str
    user: Any = None


@dataclass
class Recipient:
    """Un destinataire résolu, prêt à recevoir : à qui, et sous quelle adresse."""

    user: Any
    target: str
    trigger_scope: str = Notification.TriggerScope.USER
    trigger_role: str = ""


@dataclass
class EmitResult:
    """
    Compte rendu d'une émission. Informationnel : rien ici n'est une erreur à
    traiter par l'appelant, tout y est déjà tracé en base.
    """

    notifications_created: int = 0
    logs_created: int = 0
    logs_failed: int = 0
    idempotency_hit: bool = False
    skipped_no_recipient: bool = False
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self):
        """Représentation sérialisable, pour la journalisation applicative."""
        return {
            "notifications_created": self.notifications_created,
            "logs_created": self.logs_created,
            "logs_failed": self.logs_failed,
            "idempotency_hit": self.idempotency_hit,
            "skipped_no_recipient": self.skipped_no_recipient,
            "failure_reasons": list(self.failure_reasons),
        }


class NotificationService:
    """Service central d'émission de notifications."""

    # ─── Point d'entrée ───

    @staticmethod
    def emit(
        event_code,
        context,
        tenant=None,
        actor=None,
        recipient_override=None,
        channels=None,
        language="fr",
        idempotency_scope=None,
        deliver_now=False,
    ):
        """
        Émet un événement du catalogue.

        `channels` restreint les canaux à un sous-ensemble de ceux déclarés par
        l'événement. Sans lui, l'envoi d'un code de connexion par e-mail
        partirait aussi en SMS et sur WhatsApp — trois messages facturés là où
        un seul était demandé.

        `deliver_now` remet au fournisseur dans la foulée, sans passer par la
        file. Réservé aux envois que l'utilisateur attend à l'écran : un code de
        connexion différé de quelques secondes est un code que l'utilisateur
        croit perdu.

        `idempotency_scope` permet à l'appelant de distinguer deux émissions que
        le contexte seul ne sépare pas (deux rappels du même voyage, par
        exemple).

        Lève `KeyError` sur un code inconnu et `ValueError` sur un contexte non
        conforme : ces deux cas sont des défauts de l'appelant, pas des
        incidents de livraison.
        """
        event = catalog.get_event(event_code)
        catalog.validate_context(event_code, context)

        idempotency_key = compute_idempotency_key(
            event_code=event_code,
            actor_id=getattr(actor, "id", None),
            scope=idempotency_scope,
            context=context,
        )
        if already_emitted(idempotency_key):
            return EmitResult(idempotency_hit=True)

        result = EmitResult()

        recipients = NotificationService._resolve_recipients(
            event=event, context=context, tenant=tenant,
            recipient_override=recipient_override, result=result,
        )
        if not recipients:
            result.skipped_no_recipient = True
            return result

        target_channels = NotificationService._target_channels(event, channels)
        if not target_channels:
            # L'appelant a demandé un canal que l'événement ne déclare pas.
            # Sans cette trace, l'émission ne produirait rien du tout et
            # l'appelant croirait avoir envoyé quelque chose.
            NotificationService._fail_log(
                tenant=tenant, event_code=event.code,
                failure_reason=(
                    f"channel_not_declared:{event.code}/"
                    f"{','.join(str(c) for c in (channels or []))}"
                ),
                result=result,
            )
            return result

        for recipient in recipients:
            if not NotificationService._passes_preferences(event, recipient, tenant, result):
                continue
            NotificationService._deliver_to_recipient(
                event=event, recipient=recipient, context=context, tenant=tenant,
                channels=target_channels, language=language,
                idempotency_key=idempotency_key, result=result,
                deliver_now=deliver_now,
            )

        # Rien n'a abouti : ne pas poser la marque, pour que l'appelant puisse
        # retenter sans attendre l'expiration de la fenêtre.
        if result.logs_created:
            mark_emitted(idempotency_key)

        return result

    # ─── Étape : canaux ───

    @staticmethod
    def _target_channels(event, channels):
        declared = list(event.default_channels)
        if channels is not None:
            requested = {Channel(channel) for channel in channels}
            declared = [channel for channel in declared if channel in requested]
        return _ordered_channels(declared)

    # ─── Étape : destinataires ───

    @staticmethod
    def _resolve_recipients(event, context, tenant, recipient_override, result):
        if recipient_override is not None:
            return [
                Recipient(
                    user=recipient_override.user,
                    target=recipient_override.value,
                    trigger_scope=Notification.TriggerScope.USER,
                )
            ]

        key = event.resolver_key

        # Le registre fait foi, pas la liste des resolvers « à venir » : celle-ci
        # ne sert qu'à nommer la cause. Interroger le registre d'abord évite
        # qu'un resolver écrit au Ticket E reste inerte tant que sa clé n'a pas
        # été retirée de la liste — l'ordre des deux gestes cesse d'importer.
        try:
            resolver = get_resolver(key)
        except KeyError:
            reason = (
                f"resolver_unimplemented:{key}" if key in KNOWN_UNIMPLEMENTED_RESOLVERS
                else f"resolver_missing:{key}"
            )
            NotificationService._fail_log(
                tenant=tenant, event_code=event.code, failure_reason=reason, result=result,
            )
            return []

        try:
            resolved = resolver(context, tenant)
        except Exception as exc:  # tout échec de resolver se trace
            NotificationService._fail_log(
                tenant=tenant, event_code=event.code,
                failure_reason=f"resolver_error:{key}:{exc}", result=result,
            )
            return []

        return [
            Recipient(
                user=entry.user,
                target=NotificationService._target_for(entry.user),
                trigger_scope=entry.trigger_scope,
                trigger_role=entry.trigger_role,
            )
            for entry in resolved
        ]

    @staticmethod
    def _target_for(user):
        """Adresse d'envoi d'un compte : e-mail si connu, sinon téléphone."""
        if user is None:
            return ""
        return user.email or user.phone or str(user.pk)

    # ─── Étape : préférences (N-02) ───

    @staticmethod
    def _passes_preferences(event, recipient, tenant, result):
        user = recipient.user
        if user is None:
            return True

        preferences = getattr(user, "notification_preferences", None) or {}
        opted_out = preferences.get(event.category, True) is False

        if event.category in NEVER_OPT_OUT:
            if opted_out:
                # La base dit « non » sur une catégorie qui ne se refuse pas :
                # incohérence à corriger, mais qui ne doit pas retenir un code
                # de connexion ou une alerte de sécurité. On trace et on envoie.
                NotificationService._fail_log(
                    tenant=tenant, event_code=event.code, user=user,
                    failure_reason=f"preference_violation:{event.category}:{user.pk}",
                    result=result,
                )
            return True

        # Refus ordinaire : silencieux, c'est un choix respecté, pas un incident.
        return not opted_out

    # ─── Étape : rendu, création, mise en file ───

    @staticmethod
    def _deliver_to_recipient(
        event, recipient, context, tenant, channels, language, idempotency_key, result,
        deliver_now=False,
    ):
        notification = None

        for channel in channels:
            template = NotificationService._find_template(
                tenant=tenant, event_code=event.code, channel=channel, language=language,
            )
            if template is None:
                NotificationService._fail_log(
                    tenant=tenant, event_code=event.code, user=recipient.user,
                    channel=channel, recipient=recipient.target,
                    failure_reason=f"no_template:{event.code}/{channel}/{language}",
                    result=result,
                )
                continue

            try:
                title, body, action_url = render_for_channel(
                    template=template, context=context, event=event, channel=channel,
                )
            except Exception as exc:  # voir commentaire
                # `TemplateSyntaxError` à la construction du gabarit (syntaxe
                # invalide), mais aussi n'importe quelle erreur d'un filtre au
                # rendu sur une valeur inattendue. Les deux produisent un
                # message inexploitable : on les trace de la même façon plutôt
                # que de laisser l'une passer et l'autre remonter.
                NotificationService._fail_log(
                    tenant=tenant, event_code=event.code, user=recipient.user,
                    channel=channel, recipient=recipient.target,
                    failure_reason=f"template_error:{event.code}/{channel}/{language}:{exc}",
                    result=result,
                )
                continue

            if channel == Channel.IN_APP and recipient.user is not None:
                notification, created = NotificationService._create_notification(
                    event=event, recipient=recipient, tenant=tenant,
                    title=title, body=body, action_url=action_url,
                    idempotency_key=idempotency_key,
                )
                result.notifications_created += int(created)

            log = NotificationLog.objects.create(
                tenant=tenant, user=recipient.user, notification=notification,
                channel=channel, recipient=recipient.target, event_code=event.code,
                content=body[:500], status=NotificationLog.Status.QUEUED,
            )
            result.logs_created += 1

            NotificationService._enqueue(log, deliver_now=deliver_now)

    @staticmethod
    def _create_notification(event, recipient, tenant, title, body, action_url, idempotency_key):
        """
        Crée l'item du centre d'alertes, ou récupère celui qu'un autre worker
        vient de créer.

        La contrainte unique posée au Ticket A tranche la course que Redis ne
        peut pas arbitrer : entre le `get` et le `set`, deux workers sont tous
        deux passés. Celui qui perd récupère l'item de l'autre — un doublon
        évité, pas une erreur.

        `atomic` autour de la création : sans lui, l'IntegrityError laisse la
        transaction courante inutilisable et la requête suivante échoue.
        """
        payload = {
            "tenant": tenant,
            "event_code": event.code,
            "recipient_user": recipient.user,
            "trigger_scope": recipient.trigger_scope,
            "trigger_role": recipient.trigger_role,
            "priority": event.priority.value,
            "title": title[:200],
            "body": body,
            "action_url": action_url[:500],
            "idempotency_key": idempotency_key,
        }
        try:
            with transaction.atomic():
                return Notification.objects.create(**payload), True
        except IntegrityError:
            existing = Notification.objects.filter(
                tenant=tenant, recipient_user=recipient.user,
                idempotency_key=idempotency_key,
            ).first()
            if existing is None:
                raise
            return existing, False

    @staticmethod
    def _enqueue(log, deliver_now=False):
        """
        Met l'envoi en file, ou le remet au fournisseur immédiatement.

        Un courtier indisponible ne doit pas faire échouer l'émission : le log
        existe déjà en base au statut `queued`, une reprise pourra le retrouver.
        Perdre la notification serait pire que la livrer en retard.
        """
        from .tasks import send_notification_log

        if deliver_now:
            # Appel direct de la fonction sous-jacente : `.apply()` passerait
            # par la machinerie Celery, dont on n'a besoin ni du sérialiseur ni
            # du suivi de résultat pour un envoi qu'on attend à l'écran.
            send_notification_log(str(log.pk))
            return

        try:
            send_notification_log.delay(str(log.pk))
        except Exception:  # indisponibilité du courtier
            logger.exception(
                "Mise en file impossible pour le log %s (%s/%s)",
                log.pk, log.event_code, log.channel,
            )

    # ─── Gabarits ───

    @staticmethod
    def _find_template(tenant, event_code, channel, language):
        """
        Gabarit de la compagnie s'il existe, sinon celui du système.

        `TenantManager` ne filtre rien de lui-même : le filtre est explicite,
        et `order_by("-tenant_id")` fait passer le gabarit de la compagnie
        devant le gabarit générique (`tenant` nul).
        """
        return (
            NotificationTemplate.objects.filter(
                event_code=event_code, channel=channel, language=language, is_active=True,
            )
            .filter(Q(tenant=tenant) | Q(tenant__isnull=True))
            .order_by("-tenant_id")
            .first()
        )

    # ─── Traçabilité des échecs (N-08) ───

    @staticmethod
    def _fail_log(tenant, event_code, failure_reason, result, user=None, channel="", recipient=""):
        """Trace un échec en base et dans le compte rendu, sans jamais lever."""
        NotificationLog.objects.create(
            tenant=tenant, user=user, channel=channel or "", recipient=recipient or "",
            event_code=event_code, content="",
            status=NotificationLog.Status.FAILED,
            provider="", provider_message_id="",
            failure_reason=failure_reason[:300],
        )
        result.logs_failed += 1
        result.failure_reasons.append(failure_reason)

    # ─── Compatibilité ───

    @staticmethod
    def send_notification(tenant, event_code, channel, recipient, context_data, user=None, language="fr"):
        """
        Déprécié — utiliser `NotificationService.emit()`.

        Conservé pour les appelants pas encore migrés, la connexion par code en
        tête. L'adaptateur restreint l'émission au canal demandé et désigne le
        destinataire en clair : sans ces deux précautions, un code de connexion
        demandé par e-mail partirait aussi en SMS et sur WhatsApp.

        Retourne le dernier `NotificationLog` de cette émission, comme
        l'ancienne signature — approximation suffisante pour ses appelants, qui
        n'en lisent que le statut.
        """
        import warnings

        warnings.warn(
            "NotificationService.send_notification() est déprécié : utiliser "
            "NotificationService.emit(event_code, context, ...) avec "
            "recipient_override si le destinataire n'est pas résolu par un "
            "resolver. Retrait prévu au Ticket F.",
            DeprecationWarning,
            stacklevel=2,
        )

        target = RecipientTarget(
            type=NotificationService._guess_target_type(recipient),
            value=recipient,
            user=user,
        )
        NotificationService.emit(
            event_code=event_code,
            context=context_data,
            tenant=tenant,
            actor=user,
            recipient_override=target,
            channels=[channel],
            language=language,
            # Synchrone : les appelants historiques — la connexion par code en
            # tête — rendent la main à un utilisateur qui attend son message.
            deliver_now=True,
            # Deux codes de connexion demandés d'affilée ont un contexte
            # différent (le code change), mais le destinataire, lui, doit
            # entrer dans la clé : sans cela deux personnes recevant le même
            # code au même moment se dédupliqueraient l'une l'autre.
            idempotency_scope=f"legacy:{channel}:{recipient}",
        )

        return (
            NotificationLog.objects.filter(event_code=event_code, recipient=recipient)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def _guess_target_type(recipient):
        if "@" in recipient:
            return "email"
        if recipient.startswith("+"):
            return "phone"
        return "user"
