"""Router notes — évaluations et notes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_tenant_db, require_permission
from app.repositories.user_repository import get_teacher_profile_id
from app.schemas.grades import (
    EvaluationCreate,
    EvaluationResponse,
    GradeBatchUpdate,
    GradeResponse,
    GradesSummaryResponse,
)
from app.services import grades_service as service

router = APIRouter(tags=["grades"])


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------


@router.get("/evaluations", response_model=list[EvaluationResponse])
async def list_evaluations(
    class_id: int | None = Query(None),
    teacher_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    trimester: int | None = Query(None),
    _: None = require_permission("grades:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    return await service.list_evaluations(
        db,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )


@router.post("/evaluations", response_model=EvaluationResponse, status_code=201)
async def create_evaluation(
    data: EvaluationCreate,
    request: Request,
    _: None = require_permission("grades:write"),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Crée une évaluation.

    - Si l'auteur est un enseignant titulaire → teacher_id auto-rempli depuis son profil.
    - Sinon (admin/staff délégué) → data.teacher_id requis et validé.
    L'audit `entered_by_user_id` capture systématiquement qui crée (delegation tracking).
    """
    from fastapi import HTTPException

    teacher_id = await get_teacher_profile_id(db, current_user.user_id)
    if teacher_id is None:
        if data.teacher_id is None:
            raise HTTPException(
                status_code=400,
                detail="teacher_id requis : précisez l'enseignant titulaire de l'évaluation",
            )
        if not await service.teacher_exists(db, data.teacher_id):
            raise HTTPException(status_code=400, detail="Enseignant introuvable")
        teacher_id = data.teacher_id
    return await service.create_evaluation(
        db, data=data, teacher_id=teacher_id, current_user_id=current_user.user_id
    )


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


@router.get("/grades", response_model=list[GradeResponse])
async def get_grades(
    evaluation_id: int = Query(...),
    _: None = require_permission("grades:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    return await service.get_grades(db, eval_id=evaluation_id)


@router.patch("/grades/{evaluation_id}", response_model=list[GradeResponse])
async def batch_update_grades(
    evaluation_id: int,
    payload: GradeBatchUpdate,
    _: None = require_permission("grades:write"),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    return await service.batch_update_grades(
        db,
        eval_id=evaluation_id,
        payload=payload,
        current_user_id=current_user.user_id,
    )


@router.get("/grades/summary/{class_id}", response_model=GradesSummaryResponse)
async def get_grades_summary(
    class_id: int,
    trimester: int = Query(..., ge=1, le=3),
    academic_year_id: int = Query(...),
    _: None = require_permission("grades:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    return await service.get_summary(
        db,
        class_id=class_id,
        trimester=trimester,
        academic_year_id=academic_year_id,
    )


