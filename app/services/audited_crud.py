"""Modifier une fiche et le dire au journal, en un seul geste.

Douze services écrivaient la même dizaine de lignes : calculer l'état d'avant,
nommer le sujet, ouvrir un point de reprise, écrire, journaliser. Recopié
douze fois, ce bloc se dégrade par omission, et l'omission ne se voit pas : une
modification sans `old_values` s'enregistre sans erreur, et c'est seulement
six mois plus tard, devant une famille qui conteste un montant, que la colonne
« Avant » se révèle vide.

Ce helper ne cache rien de nouveau. Il rend simplement impossible d'oublier la
moitié qui compte.

**Il ne couvre pas les suppressions.** Elles ne partagent pas une forme :
certaines passent par `db.delete`, d'autres par le dépôt, certaines emportent
des lignes liées et le disent dans `new_values`. Les plier de force dans une
signature unique demanderait des drapeaux, c'est-à-dire exactement ce que ce
module cherche à supprimer. Elles nomment donc leurs champs à la main, via
`frozen`.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.audit_values import frozen_changed, subject_of


class Persisted(Protocol):
    """Une ligne déjà en base : c'est son identifiant que le journal retient."""

    id: int


async def audited_update(
    db: AsyncSession,
    obj: Persisted,
    changes: dict[str, Any],
    *,
    entity_type: str,
    # Le `repo.update_x` du domaine : il pose les champs et flush.
    updater: Callable[..., Awaitable[Any]],
    actor: int | None,
) -> None:
    """Applique `changes` à `obj` et laisse au journal de quoi le relire.

    L'état d'avant et le nom du sujet sont pris sur l'objet **avant** la
    mutation, et sans toucher la base : « 6e A renommée en 6e B » doit se lire
    sous le nom qu'avait la fiche au moment de l'acte, comme la colonne
    « Avant » juste à côté.

    L'identifiant journalisé est celui de `obj` : il ne peut pas diverger de
    la fiche réellement modifiée.

    L'appelant garde la main sur le `commit` et sur ce qu'il renvoie : ce
    helper couvre le geste, pas la transaction entière.
    """
    avant = frozen_changed(obj, changes)
    sujet = subject_of(obj)
    # L'identifiant se lit sur l'objet qu'on modifie. Le recevoir en plus
    # laisserait la porte ouverte a journaliser le numero d'une fiche en en
    # modifiant une autre, et rien ne le signalerait.
    entity_id = int(obj.id)
    async with db.begin_nested():
        await updater(db, obj, **changes)
        await audit_log(
            db,
            entity_type=entity_type,
            action=AuditAction.UPDATE,
            user_id=actor,
            entity_id=entity_id,
            old_values=avant,
            subject_label=sujet,
            new_values=changes,
        )
