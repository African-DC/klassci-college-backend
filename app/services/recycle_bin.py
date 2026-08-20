"""L'écran de la corbeille : tout ce qui a été mis de côté, au même endroit.

Cinq entités relèvent de la corbeille, réparties sur cinq tables sans lien
entre elles. On les interroge donc une par une, puis on fusionne et on trie en
Python plutôt qu'en écrivant une UNION SQL : l'UNION obligerait à aligner
artificiellement les colonnes de tables qui n'ont rien en commun (une
inscription n'a ni prénom ni nom), et le tri se ferait sur ce compromis. Le
coût est nul à l'échelle réelle d'une corbeille — quelques dizaines de fiches
mises de côté dans l'année, pas un journal qui grossit à chaque geste.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.archive_filter import INCLUDE_ARCHIVED
from app.models.enrollment import Enrollment
from app.models.user import Parent, StaffProfile, Student, TeacherProfile
from app.repositories.audit_repository import actor_names
from app.schemas.archive import ArchivedEntryResponse, ArchiveListResponse

#: Article affiché devant le nom, par type de fiche. Le même que celui des
#: gestes d'archivage : l'écran doit nommer la fiche comme le journal la nomme.
_ARTICLES: dict[str, tuple[type, str]] = {
    "student": (Student, "L'élève"),
    "parent": (Parent, "Le parent"),
    "teacher": (TeacherProfile, "L'enseignant"),
    "staff": (StaffProfile, "Le membre du personnel"),
}

ENTITY_TYPES: tuple[str, ...] = (*_ARTICLES, "enrollment")


def _archived_only(stmt: Select[Any]) -> Select[Any]:
    """Ne garder que les fiches mises de côté, filtre global levé.

    Sans `INCLUDE_ARCHIVED`, la corbeille serait vide par construction : le
    filtre posé sur la session masque précisément ces lignes-là.
    """
    return stmt.execution_options(**{INCLUDE_ARCHIVED: True})


async def _person_rows(db: AsyncSession, entity_type: str) -> list[dict[str, Any]]:
    model, article = _ARTICLES[entity_type]
    stmt = (
        select(
            model.id,
            model.archived_at,
            model.archived_by,
            model.archive_reason,
            model.last_name,
            model.first_name,
        )
        .where(model.archived_at.isnot(None))
        .order_by(model.archived_at.desc())
    )
    rows = (await db.execute(_archived_only(stmt))).all()
    return [
        {
            "entity_type": entity_type,
            "entity_id": int(row.id),
            "label": f"{article} {row.last_name} {row.first_name}".strip(),
            "archived_at": row.archived_at,
            "archived_by": row.archived_by,
            "reason": row.archive_reason,
        }
        for row in rows
    ]


async def _enrollment_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """L'inscription ne porte pas de nom : on va chercher celui de l'élève.

    La jointure passe par le filtre global levé, sinon une inscription
    archivée dont l'élève l'est aussi disparaîtrait de la corbeille — ce qui
    est exactement le cas où on a le plus besoin de la voir.
    """
    stmt = (
        select(
            Enrollment.id,
            Enrollment.archived_at,
            Enrollment.archived_by,
            Enrollment.archive_reason,
            Student.last_name,
            Student.first_name,
        )
        .join(Student, Student.id == Enrollment.student_id)
        .where(Enrollment.archived_at.isnot(None))
        .order_by(Enrollment.archived_at.desc())
    )
    rows = (await db.execute(_archived_only(stmt))).all()
    return [
        {
            "entity_type": "enrollment",
            "entity_id": int(row.id),
            "label": f"L'inscription de {row.last_name} {row.first_name}".strip(),
            "archived_at": row.archived_at,
            "archived_by": row.archived_by,
            "reason": row.archive_reason,
        }
        for row in rows
    ]


def ensure_known_entity_type(entity_type: str | None) -> str | None:
    """Refuse un filtre inconnu plutôt que de renvoyer une corbeille vide.

    Une liste vide se lit comme « rien à restaurer », ce qui est un mensonge
    tranquille quand la vraie cause est une faute de frappe dans le filtre.
    """
    if entity_type is None:
        return None
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Type inconnu : {entity_type}. Types disponibles : {', '.join(ENTITY_TYPES)}.",
        )
    return entity_type


async def list_bin(
    db: AsyncSession, *, entity_type: str | None = None, page: int = 1, size: int = 50
) -> ArchiveListResponse:
    """Tout ce qui est dans la corbeille, du plus récemment mis de côté."""
    wanted = ensure_known_entity_type(entity_type)

    entries: list[dict[str, Any]] = []
    for kind in _ARTICLES:
        if wanted in (None, kind):
            entries.extend(await _person_rows(db, kind))
    if wanted in (None, "enrollment"):
        entries.extend(await _enrollment_rows(db))

    # Le plus récent d'abord ; l'identifiant départage deux fiches archivées
    # dans la même seconde, pour que la pagination reste stable d'une page à
    # l'autre.
    entries.sort(key=lambda e: (e["archived_at"], e["entity_id"]), reverse=True)

    total = len(entries)
    page_entries = entries[(page - 1) * size : page * size]

    ids = {e["archived_by"] for e in page_entries if e["archived_by"]}
    noms = await actor_names(db, ids)
    return ArchiveListResponse(
        items=[
            ArchivedEntryResponse(
                **entry,
                archived_by_name=noms.get(entry["archived_by"]) if entry["archived_by"] else None,
            )
            for entry in page_entries
        ],
        total=total,
        page=page,
        size=size,
    )
