"""Archivage, restauration et suppression définitive.

Trois gestes, trois niveaux d'engagement :

- **archiver** : la fiche quitte les écrans, rien n'est détruit, on peut
  revenir dessus le lendemain ;
- **restaurer** : elle revient, sans condition ;
- **supprimer définitivement** : irréversible, réservé à l'administrateur, et
  seulement depuis la corbeille — on ne détruit jamais une fiche qu'on vient
  de voir dans une liste.

Chaque geste destructeur exige un motif, part au journal d'audit avec
l'identité figée de son auteur, et déclenche un courriel. Un mail sort du
logiciel : si quelqu'un efface une trace, il n'efface pas une boîte de
réception.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.datetimes import utcnow_naive
from app.core.exceptions import NotFoundError
from app.models.archivable import ArchivableMixin
from app.repositories import admin_repository as repo
from app.services.deletion import Dependent

logger = logging.getLogger(__name__)

# Un motif d'un mot ne dit rien. Assez court pour ne pas décourager, assez
# long pour interdire « ok » ou « test ».
MIN_REASON_LENGTH = 10


@dataclass(frozen=True, slots=True)
class ArchiveOutcome:
    """Ce qui s'est passé, pour le journal et pour le courriel.

    Porte l'auteur et l'heure plutôt que de laisser le courriel les redemander :
    le message doit décrire l'acte tel qu'il a eu lieu, pas tel qu'on le
    reconstitue une seconde plus tard.
    """

    entity_type: str
    entity_id: int
    label: str
    reason: str
    permanent: bool
    actor_id: int = 0
    occurred_at: datetime | None = None
    #: Phrases toutes faites — « 3 inscriptions », « 12 frais d'élève ».
    carried_away: tuple[str, ...] = field(default_factory=tuple)


def _clean_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Indiquez le motif en {MIN_REASON_LENGTH} caractères au moins. "
                "Il figurera dans le journal et dans le courriel envoyé à la direction."
            ),
        )
    return cleaned


def ensure_reason(reason: str | None) -> str:
    """Valide le motif avant qu'un geste destructeur ne commence.

    Exposée pour que l'appelant refuse un motif absent AVANT de détruire quoi
    que ce soit : découvrir le refus après coup ne coûterait rien grâce à la
    transaction, mais laisserait le code dans un ordre où l'on détruit avant
    de vérifier — un ordre qu'un jour quelqu'un sortira d'une transaction.
    """
    return _clean_reason(reason)


async def archive(
    db: AsyncSession,
    entity: ArchivableMixin,
    *,
    entity_type: str,
    label: str,
    reason: str | None,
    actor_id: int,
) -> ArchiveOutcome:
    """Retire la fiche des écrans sans rien détruire."""
    if entity.archived_at is not None:
        raise HTTPException(status_code=409, detail=f"{label} est déjà dans la corbeille.")

    cleaned = _clean_reason(reason)
    moment = utcnow_naive()
    entity.archived_at = moment
    entity.archived_by = actor_id
    entity.archive_reason = cleaned

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=entity.id,
        new_values={"archived": True, "label": label},
        notes=cleaned,
    )
    await db.commit()
    logger.info("Archivage %s %s par %s : %s", entity_type, entity.id, actor_id, cleaned)
    outcome = ArchiveOutcome(
        entity_type,
        entity.id,
        label,
        cleaned,
        permanent=False,
        actor_id=actor_id,
        occurred_at=moment,
    )
    await notify(db, outcome)
    return outcome


async def restore(
    db: AsyncSession,
    entity: ArchivableMixin,
    *,
    entity_type: str,
    label: str,
    actor_id: int,
) -> None:
    """Sort la fiche de la corbeille.

    Aucun motif demandé : restaurer répare, ça ne détruit rien. Exiger une
    justification pour revenir en arrière découragerait de corriger une
    erreur, ce qui est exactement l'inverse du but.
    """
    if entity.archived_at is None:
        raise HTTPException(status_code=409, detail=f"{label} n'est pas dans la corbeille.")

    entity.archived_at = None
    entity.archived_by = None
    entity.archive_reason = None

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=entity.id,
        new_values={"archived": False, "label": label},
    )
    await db.commit()


def ensure_archived_first(entity: ArchivableMixin, *, label: str) -> None:
    """Interdit la suppression définitive d'une fiche encore visible.

    Le passage par la corbeille est ce qui laisse le temps de se raviser. Le
    court-circuiter transformerait un clic malheureux en perte définitive.
    """
    if entity.archived_at is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{label} doit d'abord être placé dans la corbeille. "
                "La suppression définitive ne s'y fait qu'ensuite."
            ),
        )


async def record_permanent_deletion(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    label: str,
    reason: str | None,
    actor_id: int,
    carried_away: Sequence[Dependent] | None = None,
) -> ArchiveOutcome:
    """Journalise la suppression définitive avant qu'elle n'ait lieu.

    Écrit avant, délibérément : une fois la fiche partie, on ne peut plus
    relire son nom pour l'inscrire au journal.

    Le courriel, lui, ne part pas d'ici : l'appelant le déclenche par
    `notify()` une fois la destruction validée. Annoncer par écrit une
    suppression qui échouerait ensuite laisserait au chef d'établissement la
    trace d'un acte qui n'a jamais eu lieu — un faux dans la boîte censée
    faire foi.
    """
    cleaned = _clean_reason(reason)
    phrases = tuple(d.phrase() for d in (carried_away or ()) if d.count)
    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.DELETE,
        user_id=actor_id,
        entity_id=entity_id,
        old_values={"label": label},
        new_values={"permanent": True, "emporte": list(phrases)},
        notes=cleaned,
    )
    logger.warning(
        "Suppression definitive %s %s par %s : %s", entity_type, entity_id, actor_id, cleaned
    )
    return ArchiveOutcome(
        entity_type,
        entity_id,
        label,
        cleaned,
        permanent=True,
        actor_id=actor_id,
        occurred_at=utcnow_naive(),
        carried_away=phrases,
    )


async def notify(db: AsyncSession, outcome: ArchiveOutcome) -> None:
    """Envoie le courriel de trace sans jamais faire échouer le geste.

    L'exception est avalée ici, et nulle part ailleurs : une secrétaire qui
    corrige une fiche créée en double ne doit pas être bloquée parce qu'un
    serveur de messagerie est injoignable. Le `logger.exception` garde
    l'incident visible côté exploitation.
    """
    from app.services import deletion_notice_service

    try:
        await deletion_notice_service.send_deletion_notice(db, outcome)
    except Exception:
        logger.exception(
            "Le courriel de trace n'a pas pu partir pour %s %s — le geste reste effectue",
            outcome.entity_type,
            outcome.entity_id,
        )


# ---------------------------------------------------------------------------
# La même mécanique pour toutes les fiches qui portent une histoire
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchivableKind:
    """Ce qu'il faut savoir d'une entité pour la mettre à la corbeille.

    Écrire la mécanique une fois plutôt que cinq : archiver un parent, un
    enseignant ou une inscription obéit exactement aux mêmes règles, et cinq
    copies finiraient par diverger sur le détail qui compte, l'ordre du garde,
    le contenu du journal, le libellé rendu à l'écran.

    `naming` et `load` ne servent qu'aux entités qui sortent du cas courant :
    une inscription ne porte ni prénom ni nom, il faut aller chercher l'élève
    pour dire de qui il s'agit.
    """

    entity_type: str
    article: str  # « L'enseignant », « Le parent »...
    model: type[ArchivableMixin]
    #: Détruit la fiche et rend l'inventaire de ce qu'elle a emporté. Cet
    #: inventaire ne peut se constituer que PENDANT la destruction : c'est le
    #: seul moment où l'on sait encore combien de notes, de frais et de
    #: versements portait la fiche. Rendre `None` quand il n'y a rien à
    #: dénombrer.
    delete: Callable[[AsyncSession, ArchivableMixin], Awaitable[Sequence[Dependent] | None]]
    naming: Callable[[ArchivableMixin], str] | None = None
    load: Callable[[AsyncSession, int], Awaitable[ArchivableMixin | None]] | None = None

    def label(self, record: ArchivableMixin) -> str:
        if self.naming is not None:
            return self.naming(record)
        first = getattr(record, "first_name", "") or ""
        last = getattr(record, "last_name", "") or ""
        return f"{self.article} {last} {first}".strip()


async def _load(db: AsyncSession, kind: ArchivableKind, record_id: int) -> ArchivableMixin:
    """Charge la fiche, archivée ou non.

    On lit délibérément à travers le filtre global : sans cela, une fiche
    déjà dans la corbeille serait introuvable, donc ni restaurable ni
    supprimable.
    """
    loader = kind.load or (lambda session, ident: repo.get_archived(session, kind.model, ident))
    record = await loader(db, record_id)
    if record is None:
        raise NotFoundError(kind.model.__name__, record_id)
    return record


async def archive_record(
    db: AsyncSession, kind: ArchivableKind, record_id: int, *, reason: str | None, actor_id: int
) -> ArchiveOutcome:
    """Place la fiche dans la corbeille."""
    record = await _load(db, kind, record_id)
    return await archive(
        db,
        record,
        entity_type=kind.entity_type,
        label=kind.label(record),
        reason=reason,
        actor_id=actor_id,
    )


async def restore_record(
    db: AsyncSession, kind: ArchivableKind, record_id: int, *, actor_id: int
) -> None:
    """Sort la fiche de la corbeille."""
    record = await _load(db, kind, record_id)
    await restore(
        db,
        record,
        entity_type=kind.entity_type,
        label=kind.label(record),
        actor_id=actor_id,
    )


async def purge_record(
    db: AsyncSession, kind: ArchivableKind, record_id: int, *, reason: str | None, actor_id: int
) -> None:
    """Supprime définitivement une fiche déjà placée dans la corbeille."""
    record = await _load(db, kind, record_id)
    label = kind.label(record)
    ensure_archived_first(record, label=label)
    # Le motif est validé avant la première destruction, pas après.
    reason = ensure_reason(reason)

    async with db.begin_nested():
        carried_away = await kind.delete(db, record)
        outcome = await record_permanent_deletion(
            db,
            entity_type=kind.entity_type,
            entity_id=record_id,
            label=label,
            reason=reason,
            actor_id=actor_id,
            carried_away=carried_away,
        )
    await db.commit()
    # Le courriel part APRÈS la destruction, jamais avant : annoncer par écrit
    # une suppression qui échouerait ensuite laisserait au chef d'établissement
    # la trace d'un acte qui n'a pas eu lieu.
    await notify(db, outcome)
