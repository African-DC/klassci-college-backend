"""Service des demandes de congé (création, consultation, validation)."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.user import User
from app.repositories.user_repository import get_user_full_name
from app.schemas.leave import LeaveRequestCreate


def _base_dict(req: LeaveRequest) -> dict:
    return {
        "id": req.id,
        "user_id": req.user_id,
        "leave_type": req.leave_type,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "reason": req.reason,
        "status": req.status,
        "reviewed_by": req.reviewed_by,
        "reviewed_at": req.reviewed_at,
        "review_comment": req.review_comment,
        "created_at": req.created_at,
    }


async def _enrich_rows(db: AsyncSession, rows: list[LeaveRequest]) -> list[dict]:
    uids = {r.user_id for r in rows}
    users: dict[int, User] = {}
    if uids:
        res = (
            await db.execute(
                select(User)
                .where(User.id.in_(uids))
                .options(
                    selectinload(User.staff_profile),
                    selectinload(User.teacher_profile),
                    selectinload(User.student_profile),
                    selectinload(User.parent_profile),
                )
            )
        ).scalars().all()
        users = {u.id: u for u in res}

    out: list[dict] = []
    for r in rows:
        d = _base_dict(r)
        u = users.get(r.user_id)
        if u is not None:
            fn, ln = get_user_full_name(u)
            d["requester_name"] = f"{ln} {fn}".strip() or u.email
            d["requester_role"] = u.role
        else:
            d["requester_name"] = None
            d["requester_role"] = None
        out.append(d)
    return out


async def _get(db: AsyncSession, req_id: int) -> LeaveRequest:
    req = (
        await db.execute(select(LeaveRequest).where(LeaveRequest.id == req_id))
    ).scalar_one_or_none()
    if req is None:
        raise NotFoundError("LeaveRequest", req_id)
    return req


async def create_request(db: AsyncSession, user_id: int, data: LeaveRequestCreate) -> dict:
    req = LeaveRequest(
        user_id=user_id,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=(data.reason.strip() if data.reason else None),
        status=LeaveStatus.PENDING.value,
    )
    db.add(req)
    await db.flush()
    rid = req.id
    await db.commit()
    row = await _get(db, rid)
    return (await _enrich_rows(db, [row]))[0]


async def list_my_requests(db: AsyncSession, user_id: int) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(LeaveRequest)
                .where(LeaveRequest.user_id == user_id)
                .order_by(LeaveRequest.created_at.desc())
            )
        ).scalars().all()
    )
    return await _enrich_rows(db, rows)


async def list_all(db: AsyncSession, *, status: str | None = None) -> list[dict]:
    stmt = select(LeaveRequest).order_by(LeaveRequest.created_at.desc())
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    rows = list((await db.execute(stmt)).scalars().all())
    return await _enrich_rows(db, rows)


async def cancel_request(db: AsyncSession, user_id: int, req_id: int) -> dict:
    req = await _get(db, req_id)
    if req.user_id != user_id:
        raise NotFoundError("LeaveRequest", req_id)
    if req.status != LeaveStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Seule une demande en attente peut être annulée")
    req.status = LeaveStatus.CANCELLED.value
    await db.commit()
    row = await _get(db, req_id)
    return (await _enrich_rows(db, [row]))[0]


async def review_request(
    db: AsyncSession, req_id: int, *, reviewer_id: int, approve: bool, comment: str | None
) -> dict:
    req = await _get(db, req_id)
    if req.status != LeaveStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Cette demande a déjà été traitée")
    req.status = LeaveStatus.APPROVED.value if approve else LeaveStatus.REJECTED.value
    req.reviewed_by = reviewer_id
    req.reviewed_at = datetime.now(UTC)
    req.review_comment = comment.strip() if comment else None
    await db.commit()
    row = await _get(db, req_id)
    return (await _enrich_rows(db, [row]))[0]
