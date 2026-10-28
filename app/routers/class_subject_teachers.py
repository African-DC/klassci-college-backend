"""Enseignant retenu par classe et par matière, pour l'emploi du temps."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.class_subject_teachers import (
    ClassSubjectTeacherItem,
    ClassSubjectTeachersResponse,
    ClassSubjectTeachersUpdate,
)
from app.services import class_subject_teacher_service as service
from app.services.class_subject_teacher_service import ClassSubjectTeacherEntry

router = APIRouter(prefix="/timetable/classes", tags=["timetable"])


def _to_response(
    class_id: int, class_name: str, entries: list[ClassSubjectTeacherEntry]
) -> ClassSubjectTeachersResponse:
    items = [
        ClassSubjectTeacherItem(
            subject_id=e.subject.id,
            subject_name=e.subject.name,
            hours_per_week=e.subject.hours_per_week,
            series_name=e.subject.series.name if e.subject.series else None,
            eligible_teachers=e.eligible,
            assigned_teacher_id=e.assigned_teacher_id,
            resolved_teacher_id=e.resolved_teacher_id,
            source=e.source,
        )
        for e in entries
    ]
    return ClassSubjectTeachersResponse(
        class_id=class_id,
        class_name=class_name,
        items=items,
        missing_count=sum(1 for i in items if i.resolved_teacher_id is None),
    )


@router.get("/{class_id}/subject-teachers", response_model=ClassSubjectTeachersResponse)
async def get_class_subject_teachers(
    class_id: int,
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassSubjectTeachersResponse:
    """Matières de la classe, enseignants proposés et enseignant résolu pour chacune."""
    cls = await service.load_class_or_404(db, class_id)
    entries = await service.resolve_class_teachers(db, cls)
    return _to_response(cls.id, cls.name, entries)


@router.put("/{class_id}/subject-teachers", response_model=ClassSubjectTeachersResponse)
async def put_class_subject_teachers(
    class_id: int,
    data: ClassSubjectTeachersUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassSubjectTeachersResponse:
    """Mise à jour partielle : seules les matières listées changent (teacher_id null = retirer le choix)."""
    cls, entries = await service.save_class_teachers(
        db, class_id, data.assignments, actor=current_user.user_id
    )
    return _to_response(cls.id, cls.name, entries)
