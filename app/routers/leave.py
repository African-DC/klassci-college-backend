"""Routers des demandes de congé : self (/leave) + admin (/admin/leave)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.leave import LeaveRequestCreate, LeaveRequestResponse, LeaveReviewRequest
from app.services import leave_service

# --- Self : l'utilisateur gère ses propres demandes ---
self_router = APIRouter(prefix="/leave", tags=["leave"])


@self_router.post("/requests", response_model=LeaveRequestResponse, status_code=201)
async def create_leave_request(
    data: LeaveRequestCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("leave:request"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LeaveRequestResponse:
    return LeaveRequestResponse(**await leave_service.create_request(db, current_user.user_id, data))


@self_router.get("/requests/me", response_model=list[LeaveRequestResponse])
async def list_my_leave_requests(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[LeaveRequestResponse]:
    rows = await leave_service.list_my_requests(db, current_user.user_id)
    return [LeaveRequestResponse(**r) for r in rows]


@self_router.post("/requests/{req_id}/cancel", response_model=LeaveRequestResponse)
async def cancel_leave_request(
    req_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> LeaveRequestResponse:
    return LeaveRequestResponse(
        **await leave_service.cancel_request(db, current_user.user_id, req_id)
    )


# --- Admin / direction : consultation et validation ---
admin_router = APIRouter(prefix="/admin/leave", tags=["leave-admin"])


@admin_router.get("/requests", response_model=list[LeaveRequestResponse])
async def list_leave_requests(
    status: str | None = Query(None),
    _: None = require_permission("leave:approve"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[LeaveRequestResponse]:
    rows = await leave_service.list_all(db, status=status)
    return [LeaveRequestResponse(**r) for r in rows]


@admin_router.post("/requests/{req_id}/approve", response_model=LeaveRequestResponse)
async def approve_leave_request(
    req_id: int,
    data: LeaveReviewRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("leave:approve"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LeaveRequestResponse:
    return LeaveRequestResponse(
        **await leave_service.review_request(
            db, req_id, reviewer_id=current_user.user_id, approve=True, comment=data.comment
        )
    )


@admin_router.post("/requests/{req_id}/reject", response_model=LeaveRequestResponse)
async def reject_leave_request(
    req_id: int,
    data: LeaveReviewRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("leave:approve"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LeaveRequestResponse:
    return LeaveRequestResponse(
        **await leave_service.review_request(
            db, req_id, reviewer_id=current_user.user_id, approve=False, comment=data.comment
        )
    )
