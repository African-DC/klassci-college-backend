"""Service pointage enseignant — workflow hybride (Phase 7b).

Marcel 2026-05-19 :
- Admin/staff saisit → validé immédiatement (is_validated=True)
- Prof self-declare → en attente (is_validated=False), admin valide après
- Granularité slot EDT (slot_id nullable pour absences hors EDT)
- Retards : compteur minutes (int)
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.attendance import TeacherAttendanceStatus, TeacherSessionAttendance
from app.models.user import TeacherProfile
from app.repositories import teacher_attendance_repository as repo
from app.schemas.teacher_attendance import (
    TeacherAttendanceCreate,
    TeacherAttendanceListResponse,
    TeacherAttendanceResponse,
    TeacherAttendanceStats,
    TeacherAttendanceValidate,
    TeacherSelfDeclareCreate,
)

# ---------------------------------------------------------------------------
# Mapping ORM → Response Pydantic
# ---------------------------------------------------------------------------


def _slot_summary(att: TeacherSessionAttendance) -> str | None:
    """Compose un libellé lisible 'Lundi 10h-11h Maths 6ème B'."""
    if att.slot is None:
        return None
    s = att.slot
    day_fr = {
        "monday": "Lundi",
        "tuesday": "Mardi",
        "wednesday": "Mercredi",
        "thursday": "Jeudi",
        "friday": "Vendredi",
        "saturday": "Samedi",
        "sunday": "Dimanche",
    }
    day = day_fr.get(s.day, s.day or "")
    start = s.start_time if isinstance(s.start_time, str) else s.start_time.strftime("%H:%M")
    end = s.end_time if isinstance(s.end_time, str) else s.end_time.strftime("%H:%M")
    subject_name = s.subject.name if getattr(s, "subject", None) else ""
    class_name = s.class_.name if getattr(s, "class_", None) else ""
    parts = [day, f"{start}-{end}"]
    if subject_name:
        parts.append(subject_name)
    if class_name:
        parts.append(class_name)
    return " ".join(parts).strip()


def _to_response(att: TeacherSessionAttendance) -> TeacherAttendanceResponse:
    teacher_full = ""
    if att.teacher is not None:
        teacher_full = f"{att.teacher.first_name} {att.teacher.last_name}".strip()
    declared_email = att.declared_by.email if att.declared_by else None
    validated_email = att.validated_by.email if att.validated_by else None
    return TeacherAttendanceResponse(
        id=att.id,
        teacher_id=att.teacher_id,
        teacher_full_name=teacher_full,
        slot_id=att.slot_id,
        slot_summary=_slot_summary(att),
        date=att.date,
        academic_year_id=att.academic_year_id,
        status=att.status,  # type: ignore[arg-type]
        late_minutes=att.late_minutes,
        notes=att.notes,
        declared_by_user_id=att.declared_by_user_id,
        declared_by_email=declared_email,
        declared_at=att.declared_at,
        is_validated=att.is_validated,
        validated_by_user_id=att.validated_by_user_id,
        validated_by_email=validated_email,
        validated_at=att.validated_at,
        created_at=att.created_at,
        updated_at=att.updated_at,
    )


# ---------------------------------------------------------------------------
# Create — admin/staff (validated direct)
# ---------------------------------------------------------------------------


async def record_attendance(
    db: AsyncSession,
    teacher_id: int,
    data: TeacherAttendanceCreate,
    *,
    declared_by_user_id: int,
) -> TeacherAttendanceResponse:
    """Saisie d'un pointage par un admin ou staff.

    Workflow : `is_validated=True` instantané (l'admin EST l'autorité).
    Audit log obligatoire (sécurité.md règle).
    """
    # 1. Validation : teacher existe
    teacher_stmt = select(TeacherProfile).where(TeacherProfile.id == teacher_id)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()
    if teacher is None:
        raise NotFoundError("TeacherProfile", teacher_id)

    # 2. Validation : slot (si fourni) appartient au teacher
    if data.slot_id is not None:
        belongs = await repo.slot_belongs_to_teacher(db, data.slot_id, teacher_id)
        if not belongs:
            raise BusinessValidationError(
                "Le créneau EDT sélectionné n'appartient pas à cet enseignant."
            )

    # 3. Validation : pas de doublon (teacher, slot, date) si slot fourni
    if data.slot_id is not None:
        existing = await repo.exists_for(db, teacher_id, data.slot_id, data.date)
        if existing is not None:
            raise BusinessValidationError(
                "Un pointage existe déjà pour ce créneau à cette date. "
                "Modifiez-le ou supprimez-le d'abord."
            )

    # 4. Résoudre l'AY courante
    ay = await repo.get_current_academic_year(db)
    if ay is None:
        raise BusinessValidationError(
            "Aucune année scolaire active. Configurez-en une avant de pointer."
        )

    # 5. Créer la row
    now = datetime.utcnow()
    att = TeacherSessionAttendance(
        teacher_id=teacher_id,
        slot_id=data.slot_id,
        date=data.date,
        academic_year_id=ay.id,
        status=TeacherAttendanceStatus(data.status),
        late_minutes=data.late_minutes if data.status == "late" else 0,
        notes=data.notes,
        declared_by_user_id=declared_by_user_id,
        declared_at=now,
        is_validated=True,
        validated_by_user_id=declared_by_user_id,
        validated_at=now,
    )
    db.add(att)
    await db.flush()

    # 6. Audit log
    await audit_log(
        db,
        entity_type="teacher_session_attendance",
        action=AuditAction.CREATE,
        user_id=declared_by_user_id,
        entity_id=att.id,
        old_values=None,
        new_values=data.model_dump(mode="json"),
    )
    await db.commit()

    # 7. Refetch via repo pour selectinload exhaustif (preload-relations rule)
    refreshed = await repo.get_by_id(db, att.id)
    assert refreshed is not None
    return _to_response(refreshed)


# ---------------------------------------------------------------------------
# Create — prof self-declare (pending validation)
# ---------------------------------------------------------------------------


async def self_declare(
    db: AsyncSession,
    teacher_user_id: int,
    data: TeacherSelfDeclareCreate,
) -> TeacherAttendanceResponse:
    """Auto-déclaration par le prof — toujours `is_validated=False`.

    Le `teacher_id` est résolu depuis `teacher_user_id` (JWT current user).
    """
    teacher_stmt = select(TeacherProfile).where(TeacherProfile.user_id == teacher_user_id)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()
    if teacher is None:
        raise BusinessValidationError("Aucun profil enseignant trouvé pour cet utilisateur.")

    if data.slot_id is not None:
        belongs = await repo.slot_belongs_to_teacher(db, data.slot_id, teacher.id)
        if not belongs:
            raise BusinessValidationError(
                "Le créneau EDT sélectionné n'appartient pas à votre emploi du temps."
            )
        existing = await repo.exists_for(db, teacher.id, data.slot_id, data.date)
        if existing is not None:
            raise BusinessValidationError("Vous avez déjà déclaré ce créneau à cette date.")

    ay = await repo.get_current_academic_year(db)
    if ay is None:
        raise BusinessValidationError("Aucune année scolaire active. Contactez l'administration.")

    att = TeacherSessionAttendance(
        teacher_id=teacher.id,
        slot_id=data.slot_id,
        date=data.date,
        academic_year_id=ay.id,
        status=TeacherAttendanceStatus(data.status),
        late_minutes=data.late_minutes if data.status == "late" else 0,
        notes=data.notes,
        declared_by_user_id=teacher_user_id,
        declared_at=datetime.utcnow(),
        is_validated=False,
    )
    db.add(att)
    await db.flush()

    await audit_log(
        db,
        entity_type="teacher_session_attendance",
        action=AuditAction.CREATE,
        user_id=teacher_user_id,
        entity_id=att.id,
        old_values=None,
        new_values={"self_declared": True, **data.model_dump(mode="json")},
    )
    await db.commit()

    refreshed = await repo.get_by_id(db, att.id)
    assert refreshed is not None
    return _to_response(refreshed)


# ---------------------------------------------------------------------------
# Validate — admin approves / rejects an auto-declaration
# ---------------------------------------------------------------------------


async def validate_attendance(
    db: AsyncSession,
    attendance_id: int,
    data: TeacherAttendanceValidate,
    *,
    validated_by_user_id: int,
) -> TeacherAttendanceResponse:
    att = await repo.get_by_id(db, attendance_id)
    if att is None:
        raise NotFoundError("TeacherSessionAttendance", attendance_id)
    if att.is_validated:
        raise BusinessValidationError("Ce pointage est déjà validé.")

    old = {
        "is_validated": att.is_validated,
        "validated_by_user_id": att.validated_by_user_id,
        "validated_at": att.validated_at.isoformat() if att.validated_at else None,
    }

    att.is_validated = data.approved
    att.validated_by_user_id = validated_by_user_id
    att.validated_at = datetime.utcnow()
    if data.admin_notes:
        att.notes = (
            f"{att.notes}\n---\nAdmin: {data.admin_notes}"
            if att.notes
            else f"Admin: {data.admin_notes}"
        )

    await audit_log(
        db,
        entity_type="teacher_session_attendance",
        action=AuditAction.UPDATE,
        user_id=validated_by_user_id,
        entity_id=att.id,
        old_values=old,
        new_values={
            "is_validated": att.is_validated,
            "approved": data.approved,
            "admin_notes": data.admin_notes,
        },
    )
    await db.commit()

    refreshed = await repo.get_by_id(db, att.id)
    assert refreshed is not None
    return _to_response(refreshed)


# ---------------------------------------------------------------------------
# Delete (admin only) — annulation totale
# ---------------------------------------------------------------------------


async def delete_attendance(
    db: AsyncSession,
    attendance_id: int,
    *,
    deleted_by_user_id: int,
) -> None:
    att = await repo.get_by_id(db, attendance_id)
    if att is None:
        raise NotFoundError("TeacherSessionAttendance", attendance_id)

    await audit_log(
        db,
        entity_type="teacher_session_attendance",
        action=AuditAction.DELETE,
        user_id=deleted_by_user_id,
        entity_id=att.id,
        old_values={
            "teacher_id": att.teacher_id,
            "slot_id": att.slot_id,
            "date": att.date.isoformat(),
            "status": att.status,
            "late_minutes": att.late_minutes,
            "is_validated": att.is_validated,
        },
        new_values=None,
    )
    await db.delete(att)
    await db.commit()


# ---------------------------------------------------------------------------
# List + Stats
# ---------------------------------------------------------------------------


async def list_for_teacher(
    db: AsyncSession,
    teacher_id: int,
    academic_year_id: int | None = None,
    status: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    page: int = 1,
    per_page: int = 50,
) -> TeacherAttendanceListResponse:
    items, total = await repo.list_by_teacher(
        db,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )
    return TeacherAttendanceListResponse(
        items=[_to_response(it) for it in items],
        total=total,
    )


async def compute_stats(
    db: AsyncSession,
    teacher_id: int,
    academic_year_id: int | None = None,
) -> TeacherAttendanceStats:
    """KPIs agrégés pour la fiche teacher 360°.

    Si `academic_year_id` non fourni, prend l'AY courante.
    """
    ay = await repo.get_current_academic_year(db) if academic_year_id is None else None
    if academic_year_id is None:
        if ay is None:
            raise BusinessValidationError(
                "Aucune année scolaire active. Configurez-en une avant de consulter les statistiques."
            )
        academic_year_id = ay.id
        ay_name = ay.name
    else:
        # Refetch AY pour le name
        from app.models.academic import AcademicYear

        ay_obj = (
            await db.execute(select(AcademicYear).where(AcademicYear.id == academic_year_id))
        ).scalar_one_or_none()
        if ay_obj is None:
            raise NotFoundError("AcademicYear", academic_year_id)
        ay_name = ay_obj.name

    counts = await repo.count_by_status(db, teacher_id, academic_year_id)
    sessions_present = counts.get("present", 0)
    sessions_absent_excused = counts.get("absent_excused", 0)
    sessions_absent_unexcused = counts.get("absent_unexcused", 0)
    sessions_late = counts.get("late", 0)
    total_sessions = (
        sessions_present + sessions_absent_excused + sessions_absent_unexcused + sessions_late
    )

    attendance_rate = (
        round((sessions_present + sessions_late) / total_sessions * 100.0, 2)
        if total_sessions > 0
        else 0.0
    )

    total_late = await repo.sum_late_minutes(db, teacher_id, academic_year_id)
    avg_late = round(total_late / sessions_late, 2) if sessions_late > 0 else 0.0
    pending = await repo.count_pending_validation(db, teacher_id)

    return TeacherAttendanceStats(
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        academic_year_name=ay_name,
        total_sessions=total_sessions,
        sessions_present=sessions_present,
        sessions_absent_excused=sessions_absent_excused,
        sessions_absent_unexcused=sessions_absent_unexcused,
        sessions_late=sessions_late,
        attendance_rate=attendance_rate,
        total_late_minutes=total_late,
        avg_late_minutes_when_late=avg_late,
        pending_validation_count=pending,
    )
