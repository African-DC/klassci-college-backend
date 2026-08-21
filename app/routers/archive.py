"""Corbeille — archiver, restaurer, supprimer définitivement, toutes fiches confondues.

Un seul écran de corbeille pour les cinq entités archivables : celui qui
cherche une fiche disparue ne sait pas toujours de quelle sorte elle était, et
surtout il ne devrait pas avoir à le savoir pour la retrouver.

Et un seul chemin de code pour les trois gestes. Élève, enseignant, membre du
personnel et parent obéissent exactement aux mêmes règles — ordre du garde,
contenu du journal, courriel à la direction — que `archive_service` applique
déjà. Les quatre sortes de fiches ne diffèrent que par trois choses : le
segment d'URL, le droit qui ouvre le geste, et le `ArchivableKind` qui sait
charger et détruire. C'est exactement ce que porte le registre ci-dessous.

Les URL, elles, n'ont pas bougé : `/admin/students/{id}/archive` reste
`/admin/students/{id}/archive`. Ce qui a changé, c'est qu'elles ne sont plus
écrites quatre fois.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.admin import ArchiveRequest
from app.schemas.archive import ArchiveListResponse
from app.services import admin_service, archive_service, recycle_bin
from app.services.archive_service import ArchivableKind

router = APIRouter(prefix="/admin", tags=["archive"])


# La route littérale d'abord : `/archive` doit être déclarée avant toute route
# paramétrique du même routeur, sinon un jour l'une d'elles l'avalera.
@router.get("/archive", response_model=ArchiveListResponse)
async def list_archive(
    entity_type: str | None = Query(
        None,
        max_length=50,
        description="Ne montrer qu'une sorte de fiche : student, parent, teacher, staff, enrollment.",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    _: None = require_permission("archive:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ArchiveListResponse:
    """Corbeille paginée, de la fiche la plus récemment mise de côté à la plus ancienne."""
    return await recycle_bin.list_bin(db, entity_type=entity_type, page=page, size=size)


@dataclass(frozen=True, slots=True)
class _Bin:
    """Ce qui distingue une sorte de fiche d'une autre, et rien de plus.

    Le droit d'archiver reste celui de supprimer que l'entité avait déjà :
    archiver est réversible, ça n'a jamais mérité un droit de plus. La
    suppression définitive, elle, relève partout de `archive:purge`.
    """

    segment: str  # « students » — le segment d'URL, inchangé
    param: str  # « student_id » — le nom du paramètre de chemin, inchangé lui aussi
    designation: str  # « un élève » — pour les résumés OpenAPI
    kind: ArchivableKind
    permission: str


#: Les quatre fiches de personnes. L'inscription a sa propre corbeille dans
#: `routers/enrollments.py` : son archivage refuse en plus les inscriptions
#: validées déjà encaissées, une règle qui n'a pas d'équivalent ici.
BINS: dict[str, _Bin] = {
    "student": _Bin(
        "students", "student_id", "un élève", admin_service.STUDENT_KIND, "admin:students:delete"
    ),
    "teacher": _Bin(
        "teachers",
        "teacher_id",
        "un enseignant",
        admin_service.TEACHER_KIND,
        "admin:teachers:delete",
    ),
    "staff": _Bin(
        "staff",
        "staff_id",
        "un membre du personnel",
        admin_service.STAFF_KIND,
        "admin:staff:delete",
    ),
    "parent": _Bin(
        "parents", "parent_id", "un parent", admin_service.PARENT_KIND, "admin:parents:delete"
    ),
}

PURGE_PERMISSION = "archive:purge"


def _mount(entity: str, bin_: _Bin) -> None:
    """Expose les trois gestes d'une sorte de fiche."""
    kind = bin_.kind
    base = f"/{bin_.segment}/{{{bin_.param}}}"
    may_archive = require_permission(bin_.permission)
    may_purge = require_permission(PURGE_PERMISSION)
    # L'alias garde au paramètre de chemin le nom qu'il portait — `student_id`
    # et non `record_id` — pour que la documentation publiée ne montre pas
    # deux adresses là où il n'y en a qu'une.
    identifiant = Annotated[int, Path(alias=bin_.param)]

    @router.post(
        f"{base}/archive",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"archive_{entity}",
        summary=f"Place {bin_.designation} dans la corbeille. Réversible.",
    )
    async def _archive(
        record_id: identifiant,
        data: ArchiveRequest,
        current_user: TokenData = Depends(get_current_user),
        _: None = may_archive,
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        await archive_service.archive_record(
            db, kind, record_id, reason=data.reason, actor_id=current_user.user_id
        )

    @router.post(
        f"{base}/restore",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"restore_{entity}",
        summary=f"Sort {bin_.designation} de la corbeille.",
    )
    async def _restore(
        record_id: identifiant,
        current_user: TokenData = Depends(get_current_user),
        _: None = may_archive,
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        await archive_service.restore_record(db, kind, record_id, actor_id=current_user.user_id)

    @router.delete(
        base,
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"purge_{entity}",
        summary=f"Supprime définitivement {bin_.designation} déjà placé dans la corbeille.",
        description=(
            "Réservé à la direction : c'est le seul geste du logiciel qui ne se rattrape pas. "
            "Le motif voyage dans le corps de la requête, jamais dans l'URL : une URL finit "
            "dans les journaux d'accès du serveur et chez les intermédiaires, et « exclu pour "
            "vol » n'a rien à y faire."
        ),
    )
    async def _purge(
        record_id: identifiant,
        data: ArchiveRequest,
        current_user: TokenData = Depends(get_current_user),
        _: None = may_purge,
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        await archive_service.purge_record(
            db, kind, record_id, reason=data.reason, actor_id=current_user.user_id
        )


for _entity, _bin in BINS.items():
    _mount(_entity, _bin)
