"""Service for official student documents.

Composes data and dispatches access guards for documents like the certificat
de scolarite. PDF rendering itself lives in pdf_service for cohesion.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BusinessValidationError,
    NotFoundError,
    PermissionDeniedError,
    UnauthorizedError,
)
from app.models.enrollment import Enrollment
from app.models.user import Student, User, UserRoleEnum
from app.services import parent_portal_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_active_enrollment(db: AsyncSession, student_id: int) -> Enrollment:
    """Return the student's currently active (status=valide) enrollment.

    Raises BusinessValidationError (422) if none found, with a French message
    that an admin can show as-is to a parent at the desk.
    """
    stmt = (
        select(Enrollment)
        .where(Enrollment.student_id == student_id, Enrollment.status == "valide")
        .options(
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
        )
        .order_by(Enrollment.created_at.desc())
        .limit(1)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise BusinessValidationError(
            "Aucune inscription valide trouvée pour cet élève. "
            "Vérifiez que l'élève est inscrit à l'année scolaire courante."
        )
    return enrollment


async def verify_document_access(
    db: AsyncSession,
    *,
    current_user_id: int,
    student_id: int,
    permission_slug: str,
) -> None:
    """Hybrid access guard for student documents.

    - Admin/director/staff/teacher : require the explicit permission slug
      (e.g. ``documents:certificate``). This honors role-permission matrix
      customization per tenant.
    - Parent : must have a valid parent_student link to the requested student.
      The permission slug is **not** required for parents (they always have
      legitimate access to their own children's official documents).
    - Student : must be the very student requested.

    Raises ``PermissionDeniedError`` or ``UnauthorizedError`` when access is
    not granted.
    """
    user = await db.get(User, current_user_id)
    if user is None:
        raise UnauthorizedError("User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role in (
        UserRoleEnum.ADMIN.value,
        UserRoleEnum.STAFF.value,
        UserRoleEnum.TEACHER.value,
    ):
        # Permission-based: must hold the slug (matrix-driven).
        from app.repositories.permission_repository import check_user_permission

        if not await check_user_permission(db, current_user_id, permission_slug):
            raise PermissionDeniedError(permission_slug)
        return

    if role == UserRoleEnum.PARENT.value:
        parent = await parent_portal_service._get_parent_for_user(db, current_user_id)
        await parent_portal_service._verify_child_access(db, parent.id, student_id)
        return

    if role == UserRoleEnum.STUDENT.value:
        student = await db.get(Student, student_id)
        if student is None or student.user_id != current_user_id:
            raise PermissionDeniedError("not your document")
        return

    raise PermissionDeniedError(permission_slug)


# ---------------------------------------------------------------------------
# Document data composers
# ---------------------------------------------------------------------------


async def compose_certificate_data(
    db: AsyncSession,
    student_id: int,
) -> dict[str, Any]:
    """Compose data for the certificat de scolarite PDF.

    Reads ``Student`` + active ``Enrollment`` + ``Class`` + ``AcademicYear``.
    Raises ``NotFoundError`` if the student does not exist, or
    ``BusinessValidationError`` (422) if no active enrollment is found.
    """
    student = await db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    enrollment = await _get_active_enrollment(db, student_id)

    return {
        "student": {
            "first_name": student.first_name,
            "last_name": student.last_name,
            "birth_date": student.birth_date,
            "genre": student.genre.value if student.genre else None,
            "enrollment_number": student.enrollment_number,
            "city": student.city,
            "commune": student.commune,
        },
        "class_name": enrollment.class_.name if enrollment.class_ else "",
        "academic_year_name": enrollment.academic_year.name if enrollment.academic_year else "",
        "issued_at": datetime.utcnow(),
    }


async def compose_attendance_certificate_data(
    db: AsyncSession,
    student_id: int,
) -> dict[str, Any]:
    """Compose data for the attestation de frequentation PDF.

    Reuses the active enrollment (same as compose_certificate_data) and
    augments with the attendance summary aggregated for the same academic
    year.
    """
    from app.services.attendance_service import get_student_attendance_summary

    student = await db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    enrollment = await _get_active_enrollment(db, student_id)
    summary = await get_student_attendance_summary(
        db, student_id, academic_year_id=enrollment.academic_year_id
    )

    return {
        "student": {
            "first_name": student.first_name,
            "last_name": student.last_name,
            "birth_date": student.birth_date,
            "genre": student.genre.value if student.genre else None,
            "enrollment_number": student.enrollment_number,
            "city": student.city,
            "commune": student.commune,
        },
        "class_name": enrollment.class_.name if enrollment.class_ else "",
        "academic_year_name": enrollment.academic_year.name if enrollment.academic_year else "",
        "attendance": summary,
        "issued_at": datetime.utcnow(),
    }
