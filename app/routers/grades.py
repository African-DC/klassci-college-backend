"""Router notes — évaluations, notes et bulletins."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.dependencies import get_current_user, get_tenant_db, require_permission
from app.repositories.user_repository import get_teacher_profile_id
from app.schemas.grades import (
    BulletinGenerateRequest,
    BulletinGenerateResponse,
    BulletinTaskStatusResponse,
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
    teacher_profile_id = await get_teacher_profile_id(db, current_user.user_id)
    if teacher_profile_id is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Only teachers can create evaluations")
    return await service.create_evaluation(
        db, data=data, teacher_id=teacher_profile_id, current_user_id=current_user.user_id
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


# ---------------------------------------------------------------------------
# Bulletins
# ---------------------------------------------------------------------------


@router.post("/bulletins/generate", response_model=BulletinGenerateResponse, status_code=202)
async def generate_bulletins(
    data: BulletinGenerateRequest,
    request: Request,
    _: None = require_permission("bulletins:generate"),
) -> Any:
    tenant_id: str = getattr(request.state, "tenant_id", "local")
    return await service.generate_bulletins(
        tenant_id=tenant_id,
        class_id=data.class_id,
        trimester=data.trimester,
        academic_year_id=data.academic_year_id,
    )


@router.get("/bulletins/tasks/{task_id}", response_model=BulletinTaskStatusResponse)
async def get_bulletin_task_status(
    task_id: str,
    _: None = require_permission("bulletins:generate"),
) -> Any:
    task_result = celery_app.AsyncResult(task_id)

    status_map = {
        "PENDING": "pending",
        "STARTED": "running",
        "SUCCESS": "success",
        "FAILURE": "failed",
        "RETRY": "running",
        "REVOKED": "failed",
    }
    status = status_map.get(task_result.status, "pending")

    bulletin_urls = None
    if task_result.status == "SUCCESS" and task_result.result:
        bulletin_urls = task_result.result.get("bulletin_urls")

    return {"status": status, "bulletin_urls": bulletin_urls}
