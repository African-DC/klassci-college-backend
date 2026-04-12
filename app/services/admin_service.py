"""Service admin — logique métier CRUD pour les entités de base."""

import logging

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi import HTTPException

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.security import hash_password
from app.models.academic import AcademicYear, SchoolSettings
from app.models.user import Student, User, UserRoleEnum
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
    StudentEnrollmentFeeListResponse,
    StudentEnrollmentFeeResponse,
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


async def get_student_full(db: AsyncSession, student_id: int) -> dict:
    """Enriched student profile with user, enrollment, attendance, fees data."""
    from app.models.attendance import AttendanceRecord
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee, Payment, PaymentStatus

    # Get student with user
    stmt = select(Student).where(Student.id == student_id).options(
        selectinload(Student.user)
    )
    student = (await db.execute(stmt)).scalar_one_or_none()
    if student is None:
        raise NotFoundError("Student", student_id)

    result: dict = {
        "id": student.id,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "birth_date": student.birth_date,
        "genre": student.genre,
        "enrollment_number": student.enrollment_number,
        "photo_url": student.photo_url,
        "user_id": student.user_id,
        "created_at": student.created_at,
        "updated_at": student.updated_at,
    }

    # User account info
    if student.user:
        result["user_email"] = student.user.email
        result["user_is_active"] = student.user.is_active
        result["user_last_login"] = student.user.last_login
        result["user_created_at"] = student.user.created_at

    # Current enrollment (most recent)
    enroll_stmt = (
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .options(
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
        )
        .order_by(Enrollment.id.desc())
        .limit(1)
    )
    enrollment = (await db.execute(enroll_stmt)).scalar_one_or_none()
    if enrollment:
        result["current_class_name"] = enrollment.class_.name if enrollment.class_ else None
        result["current_academic_year"] = enrollment.academic_year.name if enrollment.academic_year else None
        result["current_enrollment_status"] = enrollment.status
        result["current_enrollment_id"] = enrollment.id

    # Attendance stats
    att_stmt = select(
        func.count().label("total"),
        func.sum(case((AttendanceRecord.status == "present", 1), else_=0)).label("present"),
        func.sum(case((AttendanceRecord.status == "absent", 1), else_=0)).label("absent"),
        func.sum(case((AttendanceRecord.status == "late", 1), else_=0)).label("late"),
    ).where(AttendanceRecord.student_id == student_id)
    att_row = (await db.execute(att_stmt)).one_or_none()
    if att_row and att_row.total:
        result["attendance_total"] = att_row.total
        result["attendance_present"] = att_row.present or 0
        result["attendance_absent"] = att_row.absent or 0
        result["attendance_late"] = att_row.late or 0
        result["attendance_rate"] = round((att_row.present or 0) / att_row.total * 100, 1) if att_row.total > 0 else 0.0

    # Financial summary
    fees_stmt = (
        select(
            func.coalesce(func.sum(EnrollmentFee.amount), 0).label("expected"),
        )
        .join(Enrollment, EnrollmentFee.enrollment_id == Enrollment.id)
        .where(Enrollment.student_id == student_id)
    )
    fees_row = (await db.execute(fees_stmt)).one_or_none()
    expected = float(fees_row.expected) if fees_row else 0.0

    paid_stmt = (
        select(
            func.coalesce(func.sum(Payment.amount), 0).label("paid"),
        )
        .join(EnrollmentFee, Payment.enrollment_fee_id == EnrollmentFee.id)
        .join(Enrollment, EnrollmentFee.enrollment_id == Enrollment.id)
        .where(Enrollment.student_id == student_id, Payment.status == PaymentStatus.COMPLETED)
    )
    paid_row = (await db.execute(paid_stmt)).one_or_none()
    paid = float(paid_row.paid) if paid_row else 0.0

    result["fees_expected"] = expected
    result["fees_paid"] = paid
    result["fees_remaining"] = expected - paid
    result["fees_rate"] = round(paid / expected * 100, 1) if expected > 0 else 0.0

    return result


async def update_student_photo(
    db: AsyncSession, student_id: int, photo_url: str | None, *, updated_by: int
) -> Student:
    """Update student photo_url."""
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)
    student.photo_url = photo_url
    await db.flush()
    await db.commit()
    return student


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


async def get_teacher_full(db: AsyncSession, teacher_id: int) -> dict:
    """Enriched teacher profile with user account and aggregated KPIs."""
    from app.models.enrollment import Enrollment
    from app.models.grade import Evaluation
    from app.models.timetable import TimetableSlot
    from app.models.user import TeacherProfile

    # Get teacher with user
    stmt = select(TeacherProfile).where(TeacherProfile.id == teacher_id).options(
        selectinload(TeacherProfile.user)
    )
    teacher = (await db.execute(stmt)).scalar_one_or_none()
    if teacher is None:
        raise NotFoundError("Teacher", teacher_id)

    result: dict = {
        "id": teacher.id,
        "user_id": teacher.user_id,
        "first_name": teacher.first_name,
        "last_name": teacher.last_name,
        "speciality": teacher.speciality,
        "phone": teacher.phone,
        "created_at": teacher.created_at,
        "updated_at": teacher.updated_at,
    }

    # User account info
    if teacher.user:
        result["user_email"] = teacher.user.email
        result["user_is_active"] = teacher.user.is_active
        result["user_last_login"] = teacher.user.last_login
        result["user_created_at"] = teacher.user.created_at

    # Count distinct classes (via timetable slots)
    classes_stmt = select(
        func.count(func.distinct(TimetableSlot.class_id))
    ).where(TimetableSlot.teacher_id == teacher_id)

    # Count distinct students in those classes (via enrollments)
    students_stmt = select(
        func.count(func.distinct(Enrollment.student_id))
    ).join(
        TimetableSlot, Enrollment.class_id == TimetableSlot.class_id
    ).where(TimetableSlot.teacher_id == teacher_id)

    # Count evaluations
    evals_stmt = select(
        func.count()
    ).where(Evaluation.teacher_id == teacher_id)

    classes_count = (await db.execute(classes_stmt)).scalar() or 0
    students_count = (await db.execute(students_stmt)).scalar() or 0
    evaluations_count = (await db.execute(evals_stmt)).scalar() or 0

    result["classes_count"] = classes_count
    result["students_count"] = students_count
    result["evaluations_count"] = evaluations_count

    return result


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


async def get_staff_full(db: AsyncSession, staff_id: int) -> dict:
    """Enriched staff profile with user account info."""
    from app.models.user import StaffProfile

    stmt = select(StaffProfile).where(StaffProfile.id == staff_id).options(
        selectinload(StaffProfile.user)
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise NotFoundError("Staff", staff_id)

    result: dict = {
        "id": staff.id,
        "user_id": staff.user_id,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
        "position": staff.position,
        "phone": staff.phone,
        "created_at": staff.created_at,
        "updated_at": staff.updated_at,
    }

    if staff.user:
        result["user_email"] = staff.user.email
        result["user_is_active"] = staff.user.is_active
        result["user_last_login"] = staff.user.last_login
        result["user_created_at"] = staff.user.created_at

    return result


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


# ---------------------------------------------------------------------------
# Student Enrollment Fees
# ---------------------------------------------------------------------------


async def get_student_enrollment_fees(
    db: AsyncSession,
    student_id: int,
) -> StudentEnrollmentFeeListResponse:
    """Retourne les frais d'inscription d'un élève avec détails de paiement."""
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee, FeeVariant, FeeCategory, Payment, PaymentStatus

    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    stmt = (
        select(EnrollmentFee)
        .join(Enrollment, EnrollmentFee.enrollment_id == Enrollment.id)
        .where(Enrollment.student_id == student_id)
        .options(
            selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category),
            selectinload(EnrollmentFee.payments),
        )
        .order_by(EnrollmentFee.enrollment_id, EnrollmentFee.id)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items: list[StudentEnrollmentFeeResponse] = []
    for ef in rows:
        category_name = (
            ef.fee_variant.category.name
            if ef.fee_variant and ef.fee_variant.category
            else "Inconnu"
        )
        paid = sum(
            float(p.amount) for p in ef.payments
            if p.status == PaymentStatus.COMPLETED
        )
        amount = float(ef.amount)
        remaining = max(0.0, amount - paid)

        items.append(
            StudentEnrollmentFeeResponse(
                id=ef.id,
                enrollment_id=ef.enrollment_id,
                category_name=category_name,
                amount=amount,
                paid=paid,
                remaining=remaining,
                status=ef.status,
            )
        )

    return StudentEnrollmentFeeListResponse(items=items)
