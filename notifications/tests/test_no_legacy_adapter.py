"""
TOUPAC Notifications — Le service n'a plus qu'un point d'entrée : `emit()`.

Sentinelle contre la réintroduction accidentelle de l'adaptateur déprécié. Un
merge qui ramènerait `send_notification()` ou son helper `_guess_target_type()`
serait rouge ici avant d'être vert ailleurs.

Le nom du fichier importe : la sentinelle vit dans un test dédié plutôt qu'au
milieu des tests fonctionnels, pour que l'échec dise sans ambiguïté ce qui a
été touché — pas « un test de service casse », mais « un contrat de projet a
été retiré ».
"""
from notifications.services import NotificationService


def test_the_deprecated_adapter_is_gone_for_good():
    """
    Un seul point d'entrée public depuis le Ticket F : `NotificationService.emit`.

    Le retour de `send_notification()` réintroduirait trois choses en même
    temps : un `DeprecationWarning` à filtrer en configuration, un chemin de
    résolution parallèle à celui du service, et l'illusion qu'un canal peut
    être imposé sans le dire explicitement à `emit(channels=[...])`.
    """
    assert not hasattr(NotificationService, "send_notification"), (
        "`send_notification` a été réintroduit — utiliser `emit()` avec "
        "`recipient_override` et `channels=[...]` pour le même effet."
    )
    assert not hasattr(NotificationService, "_guess_target_type"), (
        "`_guess_target_type` a été réintroduit — l'appelant construit "
        "lui-même son `RecipientTarget`, il connaît le canal choisi."
    )
