"""Service admin — logique métier CRUD pour les entités de base."""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.security import hash_password
from app.models.academic import AcademicYear, SchoolSettings
from app.models.user import User, UserRoleEnum
from app.repositories import admin_repository as repo
from app.schemas.admin import (
    AcademicYearCreate,
    AcademicYearListResponse,
    AcademicYearResponse,
    AcademicYearUpdate,
    ClassCreate,
    ClassListResponse,
    ClassResponse,
    ClassUpdate,
    LevelCreate,
    LevelListResponse,
    LevelResponse,
    LevelUpdate,
    StaffCreate,
    StaffListResponse,
    StaffResponse,
    StaffUpdate,
    StudentCreate,
    StudentListResponse,
    StudentResponse,
    StudentUpdate,
    SubjectCreate,
    SubjectListResponse,
    SubjectResponse,
    SubjectUpdate,
    TeacherCreate,
    TeacherListResponse,
    TeacherResponse,
    TeacherUpdate,
    EnrollmentPatternUpdate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


def _student_to_response(s: object) -> StudentResponse:
    return StudentResponse.model_validate(s)


async def list_students(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> StudentListResponse:
    students, total = await repo.list_students(db, page=page, size=size, search=search)
    return StudentListResponse(
        items=[_student_to_response(s) for s in students],
        total=total,
        page=page,
        size=size,
    )


async def get_student(db: AsyncSession, student_id: int) -> StudentResponse:
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)
    return _student_to_response(student)


async def create_student(
    db: AsyncSession, data: StudentCreate, *, created_by: int
) -> StudentResponse:
    # Check email uniqueness
    existing = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"L'email {data.email} est déjà utilisé")

    async with db.begin_nested():
        # Create user account
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRoleEnum.STUDENT,
        )
        db.add(user)
        await db.flush()

        # Create student profile linked to user
        profile_data = data.model_dump(exclude={"email", "password"})
        profile_data["user_id"] = user.id
        student = await repo.create_student(db, **profile_data)
        await audit_log(
            db,
            entity_type="student",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=student.id,
            new_values={**data.model_dump(mode="json", exclude={"password"}), "user_id": user.id},
        )
    await db.commit()
    refreshed = await repo.get_student_by_id(db, student.id)
    if refreshed is None:
        raise NotFoundError("Student", student.id)
    return _student_to_response(refreshed)


async def update_student(
    db: AsyncSession, student_id: int, data: StudentUpdate, *, updated_by: int
) -> StudentResponse:
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _student_to_response(student)
    async with db.begin_nested():
        await repo.update_student(db, student, **changes)
        await audit_log(
            db,
            entity_type="student",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=student_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_student_by_id(db, student_id)
    if refreshed is None:
        raise NotFoundError("Student", student_id)
    return _student_to_response(refreshed)


async def delete_student(
    db: AsyncSession, student_id: int, *, deleted_by: int
) -> None:
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)
    async with db.begin_nested():
        await repo.delete_student(db, student)
        await audit_log(
            db,
            entity_type="student",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=student_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# TeacherProfile
# ---------------------------------------------------------------------------


def _teacher_to_response(t: object) -> TeacherResponse:
    return TeacherResponse.model_validate(t)


async def list_teachers(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> TeacherListResponse:
    teachers, total = await repo.list_teachers(db, page=page, size=size, search=search)
    return TeacherListResponse(
        items=[_teacher_to_response(t) for t in teachers],
        total=total,
        page=page,
        size=size,
    )


async def get_teacher(db: AsyncSession, teacher_id: int) -> TeacherResponse:
    teacher = await repo.get_teacher_by_id(db, teacher_id)
    if teacher is None:
        raise NotFoundError("Teacher", teacher_id)
    return _teacher_to_response(teacher)


async def create_teacher(
    db: AsyncSession, data: TeacherCreate, *, created_by: int
) -> TeacherResponse:
    # Check email uniqueness
    existing = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"L'email {data.email} est déjà utilisé")

    async with db.begin_nested():
        # Create user account
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRoleEnum.TEACHER,
        )
        db.add(user)
        await db.flush()

        # Create teacher profile linked to user
        profile_data = data.model_dump(exclude={"email", "password"})
        profile_data["user_id"] = user.id
        teacher = await repo.create_teacher(db, **profile_data)
        await audit_log(
            db,
            entity_type="teacher",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=teacher.id,
            new_values={**data.model_dump(mode="json", exclude={"password"}), "user_id": user.id},
        )
    await db.commit()
    refreshed = await repo.get_teacher_by_id(db, teacher.id)
    if refreshed is None:
        raise NotFoundError("Teacher", teacher.id)
    return _teacher_to_response(refreshed)


async def update_teacher(
    db: AsyncSession, teacher_id: int, data: TeacherUpdate, *, updated_by: int
) -> TeacherResponse:
    teacher = await repo.get_teacher_by_id(db, teacher_id)
    if teacher is None:
        raise NotFoundError("Teacher", teacher_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _teacher_to_response(teacher)
    async with db.begin_nested():
        await repo.update_teacher(db, teacher, **changes)
        await audit_log(
            db,
            entity_type="teacher",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=teacher_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_teacher_by_id(db, teacher_id)
    if refreshed is None:
        raise NotFoundError("Teacher", teacher_id)
    return _teacher_to_response(refreshed)


async def delete_teacher(
    db: AsyncSession, teacher_id: int, *, deleted_by: int
) -> None:
    teacher = await repo.get_teacher_by_id(db, teacher_id)
    if teacher is None:
        raise NotFoundError("Teacher", teacher_id)
    async with db.begin_nested():
        await repo.delete_teacher(db, teacher)
        await audit_log(
            db,
            entity_type="teacher",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=teacher_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# StaffProfile
# ---------------------------------------------------------------------------


def _staff_to_response(s: object) -> StaffResponse:
    return StaffResponse.model_validate(s)


async def list_staff(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> StaffListResponse:
    staff_list, total = await repo.list_staff(db, page=page, size=size, search=search)
    return StaffListResponse(
        items=[_staff_to_response(s) for s in staff_list],
        total=total,
        page=page,
        size=size,
    )


async def get_staff(db: AsyncSession, staff_id: int) -> StaffResponse:
    staff = await repo.get_staff_by_id(db, staff_id)
    if staff is None:
        raise NotFoundError("Staff", staff_id)
    return _staff_to_response(staff)


async def create_staff(
    db: AsyncSession, data: StaffCreate, *, created_by: int
) -> StaffResponse:
    async with db.begin_nested():
        staff = await repo.create_staff(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="staff",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=staff.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_staff_by_id(db, staff.id)
    if refreshed is None:
        raise NotFoundError("Staff", staff.id)
    return _staff_to_response(refreshed)


async def update_staff(
    db: AsyncSession, staff_id: int, data: StaffUpdate, *, updated_by: int
) -> StaffResponse:
    staff = await repo.get_staff_by_id(db, staff_id)
    if staff is None:
        raise NotFoundError("Staff", staff_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _staff_to_response(staff)
    async with db.begin_nested():
        await repo.update_staff(db, staff, **changes)
        await audit_log(
            db,
            entity_type="staff",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=staff_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_staff_by_id(db, staff_id)
    if refreshed is None:
        raise NotFoundError("Staff", staff_id)
    return _staff_to_response(refreshed)


async def delete_staff(
    db: AsyncSession, staff_id: int, *, deleted_by: int
) -> None:
    staff = await repo.get_staff_by_id(db, staff_id)
    if staff is None:
        raise NotFoundError("Staff", staff_id)
    async with db.begin_nested():
        await repo.delete_staff(db, staff)
        await audit_log(
            db,
            entity_type="staff",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=staff_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


def _class_to_response(c: object) -> ClassResponse:
    return ClassResponse.model_validate(c)


async def list_classes(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
    academic_year_id: int | None = None,
) -> ClassListResponse:
    classes, total = await repo.list_classes(
        db, page=page, size=size, level_id=level_id, academic_year_id=academic_year_id
    )
    return ClassListResponse(
        items=[_class_to_response(c) for c in classes],
        total=total,
        page=page,
        size=size,
    )


async def get_class(db: AsyncSession, class_id: int) -> ClassResponse:
    cls = await repo.get_class_by_id(db, class_id)
    if cls is None:
        raise NotFoundError("Class", class_id)
    return _class_to_response(cls)


async def create_class(
    db: AsyncSession, data: ClassCreate, *, created_by: int
) -> ClassResponse:
    async with db.begin_nested():
        cls = await repo.create_class(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="class",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=cls.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_class_by_id(db, cls.id)
    if refreshed is None:
        raise NotFoundError("Class", cls.id)
    return _class_to_response(refreshed)


async def update_class(
    db: AsyncSession, class_id: int, data: ClassUpdate, *, updated_by: int
) -> ClassResponse:
    cls = await repo.get_class_by_id(db, class_id)
    if cls is None:
        raise NotFoundError("Class", class_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _class_to_response(cls)
    async with db.begin_nested():
        await repo.update_class(db, cls, **changes)
        await audit_log(
            db,
            entity_type="class",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=class_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_class_by_id(db, class_id)
    if refreshed is None:
        raise NotFoundError("Class", class_id)
    return _class_to_response(refreshed)


async def delete_class(
    db: AsyncSession, class_id: int, *, deleted_by: int
) -> None:
    cls = await repo.get_class_by_id(db, class_id)
    if cls is None:
        raise NotFoundError("Class", class_id)
    async with db.begin_nested():
        await repo.delete_class(db, cls)
        await audit_log(
            db,
            entity_type="class",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=class_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


def _subject_to_response(s: object) -> SubjectResponse:
    return SubjectResponse.model_validate(s)


async def list_subjects(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
) -> SubjectListResponse:
    subjects, total = await repo.list_subjects(db, page=page, size=size, level_id=level_id)
    return SubjectListResponse(
        items=[_subject_to_response(s) for s in subjects],
        total=total,
        page=page,
        size=size,
    )


async def get_subject(db: AsyncSession, subject_id: int) -> SubjectResponse:
    subject = await repo.get_subject_by_id(db, subject_id)
    if subject is None:
        raise NotFoundError("Subject", subject_id)
    return _subject_to_response(subject)


async def create_subject(
    db: AsyncSession, data: SubjectCreate, *, created_by: int
) -> SubjectResponse:
    async with db.begin_nested():
        subject = await repo.create_subject(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="subject",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=subject.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_subject_by_id(db, subject.id)
    if refreshed is None:
        raise NotFoundError("Subject", subject.id)
    return _subject_to_response(refreshed)


async def update_subject(
    db: AsyncSession, subject_id: int, data: SubjectUpdate, *, updated_by: int
) -> SubjectResponse:
    subject = await repo.get_subject_by_id(db, subject_id)
    if subject is None:
        raise NotFoundError("Subject", subject_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _subject_to_response(subject)
    async with db.begin_nested():
        await repo.update_subject(db, subject, **changes)
        await audit_log(
            db,
            entity_type="subject",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=subject_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_subject_by_id(db, subject_id)
    if refreshed is None:
        raise NotFoundError("Subject", subject_id)
    return _subject_to_response(refreshed)


async def delete_subject(
    db: AsyncSession, subject_id: int, *, deleted_by: int
) -> None:
    subject = await repo.get_subject_by_id(db, subject_id)
    if subject is None:
        raise NotFoundError("Subject", subject_id)
    async with db.begin_nested():
        await repo.delete_subject(db, subject)
        await audit_log(
            db,
            entity_type="subject",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=subject_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


def _academic_year_to_response(a: object) -> AcademicYearResponse:
    return AcademicYearResponse.model_validate(a)


async def list_academic_years(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> AcademicYearListResponse:
    years, total = await repo.list_academic_years(db, page=page, size=size)
    return AcademicYearListResponse(
        items=[_academic_year_to_response(a) for a in years],
        total=total,
        page=page,
        size=size,
    )


async def get_academic_year(db: AsyncSession, year_id: int) -> AcademicYearResponse:
    year = await repo.get_academic_year_by_id(db, year_id)
    if year is None:
        raise NotFoundError("AcademicYear", year_id)
    return _academic_year_to_response(year)


async def create_academic_year(
    db: AsyncSession, data: AcademicYearCreate, *, created_by: int
) -> AcademicYearResponse:
    async with db.begin_nested():
        year = await repo.create_academic_year(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="academic_year",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=year.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_academic_year_by_id(db, year.id)
    if refreshed is None:
        raise NotFoundError("AcademicYear", year.id)
    return _academic_year_to_response(refreshed)


async def update_academic_year(
    db: AsyncSession, year_id: int, data: AcademicYearUpdate, *, updated_by: int
) -> AcademicYearResponse:
    year = await repo.get_academic_year_by_id(db, year_id)
    if year is None:
        raise NotFoundError("AcademicYear", year_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _academic_year_to_response(year)
    async with db.begin_nested():
        await repo.update_academic_year(db, year, **changes)
        await audit_log(
            db,
            entity_type="academic_year",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=year_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_academic_year_by_id(db, year_id)
    if refreshed is None:
        raise NotFoundError("AcademicYear", year_id)
    return _academic_year_to_response(refreshed)


async def delete_academic_year(
    db: AsyncSession, year_id: int, *, deleted_by: int
) -> None:
    year = await repo.get_academic_year_by_id(db, year_id)
    if year is None:
        raise NotFoundError("AcademicYear", year_id)
    async with db.begin_nested():
        await repo.delete_academic_year(db, year)
        await audit_log(
            db,
            entity_type="academic_year",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=year_id,
        )
    await db.commit()


async def get_current_academic_year(db: AsyncSession) -> AcademicYearResponse:
    """Retourne l'annee scolaire courante ou leve 404."""
    stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    result = await db.execute(stmt)
    year = result.scalar_one_or_none()
    if year is None:
        raise BusinessValidationError(
            "Aucune annee academique courante definie. "
            "Veuillez configurer l'annee courante dans les parametres."
        )
    return _academic_year_to_response(year)


async def set_current_academic_year(
    db: AsyncSession, year_id: int, *, updated_by: int
) -> AcademicYearResponse:
    """Definit une annee scolaire comme courante, desactive toutes les autres."""
    year = await repo.get_academic_year_by_id(db, year_id)
    if year is None:
        raise NotFoundError("AcademicYear", year_id)

    async with db.begin_nested():
        # Reset all years to not current
        stmt = update(AcademicYear).values(is_current=False)
        await db.execute(stmt)
        # Set this year as current
        stmt = (
            update(AcademicYear)
            .where(AcademicYear.id == year_id)
            .values(is_current=True)
        )
        await db.execute(stmt)
        await audit_log(
            db,
            entity_type="academic_year",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=year_id,
            new_values={"is_current": True},
        )
    await db.commit()

    refreshed = await repo.get_academic_year_by_id(db, year_id)
    if refreshed is None:
        raise NotFoundError("AcademicYear", year_id)
    return _academic_year_to_response(refreshed)


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------


def _level_to_response(l: object) -> LevelResponse:
    return LevelResponse.model_validate(l)


async def list_levels(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> LevelListResponse:
    levels, total = await repo.list_levels(db, page=page, size=size)
    return LevelListResponse(
        items=[_level_to_response(l) for l in levels],
        total=total,
        page=page,
        size=size,
    )


async def get_level(db: AsyncSession, level_id: int) -> LevelResponse:
    level = await repo.get_level_by_id(db, level_id)
    if level is None:
        raise NotFoundError("Level", level_id)
    return _level_to_response(level)


async def create_level(
    db: AsyncSession, data: LevelCreate, *, created_by: int
) -> LevelResponse:
    async with db.begin_nested():
        level = await repo.create_level(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="level",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=level.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_level_by_id(db, level.id)
    if refreshed is None:
        raise NotFoundError("Level", level.id)
    return _level_to_response(refreshed)


async def update_level(
    db: AsyncSession, level_id: int, data: LevelUpdate, *, updated_by: int
) -> LevelResponse:
    level = await repo.get_level_by_id(db, level_id)
    if level is None:
        raise NotFoundError("Level", level_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _level_to_response(level)
    async with db.begin_nested():
        await repo.update_level(db, level, **changes)
        await audit_log(
            db,
            entity_type="level",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=level_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_level_by_id(db, level_id)
    if refreshed is None:
        raise NotFoundError("Level", level_id)
    return _level_to_response(refreshed)


async def delete_level(
    db: AsyncSession, level_id: int, *, deleted_by: int
) -> None:
    level = await repo.get_level_by_id(db, level_id)
    if level is None:
        raise NotFoundError("Level", level_id)
    async with db.begin_nested():
        await repo.delete_level(db, level)
        await audit_log(
            db,
            entity_type="level",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=level_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Enrollment Number Pattern
# ---------------------------------------------------------------------------


async def get_school_settings(db: AsyncSession) -> SchoolSettings:
    """Get the school settings singleton. Raises NotFoundError if not provisioned."""
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    school = result.scalar_one_or_none()
    if school is None:
        raise NotFoundError("SchoolSettings", 0)
    return school


async def update_school_info(
    db: AsyncSession, data: "SchoolInfoUpdate", *, updated_by: int
) -> SchoolSettings:
    """Update general school info fields (name, address, phone, email, logo, ministry_code)."""
    school = await get_school_settings(db)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        return school
    async with db.begin_nested():
        for key, value in changes.items():
            setattr(school, key, value)
        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=school.id,
            new_values=changes,
        )
    await db.commit()
    # Re-fetch to get updated timestamps
    return await get_school_settings(db)


async def update_enrollment_pattern(
    db: AsyncSession, data: EnrollmentPatternUpdate, *, updated_by: int
) -> dict:
    """Update the enrollment number auto-generation pattern in school settings."""
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    school = result.scalar_one_or_none()
    if school is None:
        raise NotFoundError("SchoolSettings", 0)

    old_pattern = school.enrollment_number_pattern
    old_counter = school.enrollment_number_counter

    async with db.begin_nested():
        school.enrollment_number_pattern = data.pattern
        if data.reset_counter:
            school.enrollment_number_counter = 0
        await db.flush()

        await audit_log(
            db,
            entity_type="school_settings",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=school.id,
            old_values={
                "enrollment_number_pattern": old_pattern,
                "enrollment_number_counter": old_counter,
            },
            new_values={
                "enrollment_number_pattern": data.pattern,
                "enrollment_number_counter": 0 if data.reset_counter else old_counter,
            },
        )

    await db.commit()
    return {
        "pattern": school.enrollment_number_pattern,
        "counter": school.enrollment_number_counter,
        "message": "Pattern updated successfully",
    }
