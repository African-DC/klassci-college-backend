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
from app.models.user import Parent, ParentStudent, Student, StaffProfile, TeacherProfile, User, UserRoleEnum
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
    ParentCreate,
    ParentFullResponse,
    ParentListResponse,
    ParentResponse,
    ParentUpdate,
    PermissionResponse,
    RoleCreate,
    RoleListResponse,
    RoleResponse,
    RoleUpdate,
    SeriesCreate,
    SeriesListResponse,
    SeriesResponse,
    SeriesUpdate,
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
    SubjectDuplicateRequest,
    SubjectListResponse,
    SubjectResponse,
    SubjectUpdate,
    TeacherCreate,
    TeacherListResponse,
    TeacherResponse,
    TeacherUpdate,
    EnrollmentPatternUpdate,
    RoomBatchCreateResponse,
    RoomCreate,
    RoomListResponse,
    RoomResponse,
    RoomUpdate,
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


async def update_teacher_photo(
    db: AsyncSession, teacher_id: int, photo_url: str | None, *, updated_by: int
) -> TeacherProfile:
    """Update teacher photo_url."""
    teacher = await repo.get_teacher_by_id(db, teacher_id)
    if teacher is None:
        raise NotFoundError("Teacher", teacher_id)
    teacher.photo_url = photo_url
    await db.flush()
    await db.commit()
    return teacher


async def update_staff_photo(
    db: AsyncSession, staff_id: int, photo_url: str | None, *, updated_by: int
) -> StaffProfile:
    """Update staff photo_url."""
    staff = await repo.get_staff_by_id(db, staff_id)
    if staff is None:
        raise NotFoundError("Staff", staff_id)
    staff.photo_url = photo_url
    await db.flush()
    await db.commit()
    return staff


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

    # Hours per week (sum of subject hours_per_week via SubjectInstance)
    from app.models.academic import SubjectInstance
    hours_stmt = select(
        func.coalesce(func.sum(SubjectInstance.hours_per_week), 0)
    ).where(SubjectInstance.teacher_id == teacher_id)
    result["hours_per_week"] = float((await db.execute(hours_stmt)).scalar() or 0)

    # Availability rate
    from app.models.timetable import TeacherAvailability
    total_avail_stmt = select(func.count()).select_from(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id
    )
    available_stmt = select(func.count()).select_from(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.available == True,
    )
    total_avail = (await db.execute(total_avail_stmt)).scalar() or 0
    available_count = (await db.execute(available_stmt)).scalar() or 0
    result["availability_rate"] = round((available_count / total_avail * 100) if total_avail > 0 else 0, 1)

    # Include photo_url
    result["photo_url"] = teacher.photo_url

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
# Parent
# ---------------------------------------------------------------------------


def _parent_to_response(p: object) -> ParentResponse:
    return ParentResponse.model_validate(p)


async def list_parents(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> ParentListResponse:
    parents, total = await repo.list_parents(db, page=page, size=size, search=search)
    return ParentListResponse(
        items=[_parent_to_response(p) for p in parents],
        total=total,
        page=page,
        size=size,
    )


async def get_parent(db: AsyncSession, parent_id: int) -> ParentResponse:
    parent = await repo.get_parent_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError("Parent", parent_id)
    return _parent_to_response(parent)


async def get_parent_full(db: AsyncSession, parent_id: int) -> dict:
    """Enriched parent profile with user account and children list."""
    stmt = select(Parent).where(Parent.id == parent_id).options(
        selectinload(Parent.user),
        selectinload(Parent.children).selectinload(ParentStudent.student),
    )
    parent = (await db.execute(stmt)).scalar_one_or_none()
    if parent is None:
        raise NotFoundError("Parent", parent_id)

    result: dict = {
        "id": parent.id,
        "user_id": parent.user_id,
        "first_name": parent.first_name,
        "last_name": parent.last_name,
        "phone": parent.phone,
        "email": parent.email,
        "created_at": parent.created_at,
        "updated_at": parent.updated_at,
    }

    if parent.user:
        result["user_email"] = parent.user.email
        result["user_is_active"] = parent.user.is_active

    children = []
    for link in parent.children:
        s = link.student
        children.append({
            "student_id": s.id,
            "student_name": f"{s.first_name} {s.last_name}",
            "relationship_type": link.relationship_type,
        })
    result["children"] = children

    return result


async def create_parent(
    db: AsyncSession, data: ParentCreate, *, created_by: int
) -> ParentResponse:
    async with db.begin_nested():
        user_id = None

        # If email + password provided, create a User account
        if data.email and data.password:
            existing = (
                await db.execute(select(User).where(User.email == data.email))
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"L'email {data.email} est déjà utilisé",
                )

            user = User(
                email=data.email,
                hashed_password=hash_password(data.password),
                role=UserRoleEnum.PARENT,
            )
            db.add(user)
            await db.flush()
            user_id = user.id

            # Assign parent role via user_roles table
            from app.models.permission import Role, UserRole as UserRoleModel

            role_stmt = select(Role).where(Role.name == "parent")
            role = (await db.execute(role_stmt)).scalar_one_or_none()
            if role:
                db.add(UserRoleModel(user_id=user.id, role_id=role.id))
                await db.flush()

        parent = await repo.create_parent(
            db,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            email=data.email,
            user_id=user_id,
        )
        await audit_log(
            db,
            entity_type="parent",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=parent.id,
            new_values={
                **data.model_dump(mode="json", exclude={"password"}),
                "user_id": user_id,
            },
        )
    await db.commit()
    refreshed = await repo.get_parent_by_id(db, parent.id)
    if refreshed is None:
        raise NotFoundError("Parent", parent.id)
    return _parent_to_response(refreshed)


async def update_parent(
    db: AsyncSession, parent_id: int, data: ParentUpdate, *, updated_by: int
) -> ParentResponse:
    parent = await repo.get_parent_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError("Parent", parent_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _parent_to_response(parent)
    async with db.begin_nested():
        await repo.update_parent(db, parent, **changes)
        await audit_log(
            db,
            entity_type="parent",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=parent_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_parent_by_id(db, parent_id)
    if refreshed is None:
        raise NotFoundError("Parent", parent_id)
    return _parent_to_response(refreshed)


async def delete_parent(
    db: AsyncSession, parent_id: int, *, deleted_by: int
) -> None:
    parent = await repo.get_parent_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError("Parent", parent_id)
    async with db.begin_nested():
        await repo.delete_parent(db, parent)
        await audit_log(
            db,
            entity_type="parent",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=parent_id,
        )
    await db.commit()


async def link_parent_to_student(
    db: AsyncSession,
    parent_id: int,
    student_id: int,
    relationship_type: str = "guardian",
    *,
    linked_by: int,
) -> dict:
    """Create a ParentStudent link."""
    parent = await repo.get_parent_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError("Parent", parent_id)
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    # Check if link already exists — update relationship_type if so
    existing = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == parent_id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        old_type = existing.relationship_type
        existing.relationship_type = relationship_type
        async with db.begin_nested():
            await db.flush()
            await audit_log(
                db,
                entity_type="parent_student",
                action=AuditAction.UPDATE,
                user_id=linked_by,
                entity_id=parent_id,
                old_values={"relationship_type": old_type},
                new_values={"relationship_type": relationship_type},
            )
        await db.commit()
        return {"parent_id": parent_id, "student_id": student_id, "relationship_type": relationship_type}

    async with db.begin_nested():
        link = ParentStudent(
            parent_id=parent_id,
            student_id=student_id,
            relationship_type=relationship_type,
        )
        db.add(link)
        await db.flush()
        await audit_log(
            db,
            entity_type="parent_student",
            action=AuditAction.CREATE,
            user_id=linked_by,
            entity_id=parent_id,
            new_values={
                "parent_id": parent_id,
                "student_id": student_id,
                "relationship_type": relationship_type,
            },
        )
    await db.commit()
    return {"parent_id": parent_id, "student_id": student_id, "relationship_type": relationship_type}


async def unlink_parent_from_student(
    db: AsyncSession,
    parent_id: int,
    student_id: int,
    *,
    unlinked_by: int,
) -> None:
    """Remove a ParentStudent link."""
    link = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == parent_id,
                ParentStudent.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("ParentStudent link", parent_id)

    async with db.begin_nested():
        await db.delete(link)
        await db.flush()
        await audit_log(
            db,
            entity_type="parent_student",
            action=AuditAction.DELETE,
            user_id=unlinked_by,
            entity_id=parent_id,
            new_values={
                "parent_id": parent_id,
                "student_id": student_id,
            },
        )
    await db.commit()


async def get_student_parents(db: AsyncSession, student_id: int) -> list[dict]:
    """List parents linked to a student."""
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    rows = await repo.get_student_parents(db, student_id)
    return [
        {
            **_parent_to_response(parent).model_dump(mode="json"),
            "relationship_type": rel_type,
        }
        for parent, rel_type in rows
    ]


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


def _class_to_response(c: object, enrolled_count: int = 0) -> ClassResponse:
    level_name = None
    series_name = None
    academic_year_name = None
    if hasattr(c, "level") and c.level is not None:
        level_name = c.level.name
    if hasattr(c, "series") and c.series is not None:
        series_name = c.series.name
    if hasattr(c, "academic_year") and c.academic_year is not None:
        academic_year_name = c.academic_year.name
    return ClassResponse(
        id=c.id,
        name=c.name,
        level_id=c.level_id,
        series_id=c.series_id,
        academic_year_id=c.academic_year_id,
        room_id=c.room_id,
        max_students=c.max_students,
        level_name=level_name,
        series_name=series_name,
        academic_year_name=academic_year_name,
        enrolled_count=enrolled_count,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _get_enrolled_counts(
    db: AsyncSession, class_ids: list[int]
) -> dict[int, int]:
    """Retourne le nombre d'inscriptions actives par classe."""
    if not class_ids:
        return {}
    from app.models.enrollment import Enrollment

    active_statuses = ("prospect", "en_validation", "valide")
    stmt = (
        select(Enrollment.class_id, func.count(Enrollment.id))
        .where(
            Enrollment.class_id.in_(class_ids),
            Enrollment.status.in_(active_statuses),
        )
        .group_by(Enrollment.class_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: row[1] for row in rows}


async def list_classes(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
    academic_year_id: int | None = None,
    search: str | None = None,
) -> ClassListResponse:
    classes, total = await repo.list_classes(
        db, page=page, size=size, level_id=level_id, academic_year_id=academic_year_id, search=search
    )
    counts = await _get_enrolled_counts(db, [c.id for c in classes])
    return ClassListResponse(
        items=[_class_to_response(c, enrolled_count=counts.get(c.id, 0)) for c in classes],
        total=total,
        page=page,
        size=size,
    )


async def get_class(db: AsyncSession, class_id: int) -> ClassResponse:
    cls = await repo.get_class_by_id(db, class_id)
    if cls is None:
        raise NotFoundError("Class", class_id)
    counts = await _get_enrolled_counts(db, [cls.id])
    return _class_to_response(cls, enrolled_count=counts.get(cls.id, 0))


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
    r = SubjectResponse.model_validate(s)
    if hasattr(s, "level") and s.level:  # type: ignore[union-attr]
        r.level_name = s.level.name  # type: ignore[union-attr]
    if hasattr(s, "series") and s.series:  # type: ignore[union-attr]
        r.series_name = s.series.name  # type: ignore[union-attr]
    if hasattr(s, "teacher") and s.teacher:  # type: ignore[union-attr]
        t = s.teacher  # type: ignore[union-attr]
        r.teacher_name = f"{t.first_name} {t.last_name}"
        r.teacher_id = t.id
    return r


async def list_subjects(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
    search: str | None = None,
) -> SubjectListResponse:
    subjects, total = await repo.list_subjects(db, page=page, size=size, level_id=level_id, search=search)
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


async def duplicate_subject(
    db: AsyncSession, data: SubjectDuplicateRequest, *, created_by: int
) -> SubjectResponse:
    """Clone une matière dans un autre niveau/série."""
    source = await repo.get_subject_by_id(db, data.subject_id)
    if source is None:
        raise NotFoundError("Subject", data.subject_id)

    # Check for duplicate (same name in same level+series)
    existing, _ = await repo.list_subjects(db, page=1, size=1, level_id=data.level_id)
    for s in existing:
        if s.name == source.name and s.series_id == data.series_id:
            raise BusinessValidationError(
                f"La matière '{source.name}' existe déjà dans ce niveau/série"
            )

    # Fetch all to check properly (the above only checks page 1)
    all_subjects, _ = await repo.list_subjects(db, page=1, size=100, level_id=data.level_id)
    for s in all_subjects:
        if s.name == source.name and s.series_id == data.series_id:
            raise BusinessValidationError(
                f"La matière '{source.name}' existe déjà dans ce niveau/série"
            )

    new_subject = await repo.create_subject(
        db,
        name=source.name,
        coefficient=data.coefficient or source.coefficient,
        hours_per_week=data.hours_per_week or source.hours_per_week,
        color=source.color,
        level_id=data.level_id,
        series_id=data.series_id,
        teacher_id=data.teacher_id,
    )
    await audit_log(
        db,
        entity_type="subject",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=new_subject.id,
        new_values={"duplicated_from": data.subject_id, "level_id": data.level_id},
    )
    await db.commit()
    # Re-fetch with relationships loaded
    loaded = await repo.get_subject_by_id(db, new_subject.id)
    return _subject_to_response(loaded)


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
    """Retourne les frais d'inscription d'un élève avec détails de paiement.

    Inclut les frais obligatoires (EnrollmentFee) ET les options facultatives
    souscrites (StudentOption).
    """
    from app.models.enrollment import Enrollment, StudentOption
    from app.models.fee import EnrollmentFee, FeeVariant, FeeCategory, OptionalFeeOption, Payment, PaymentStatus

    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    # 1. Frais obligatoires (EnrollmentFee)
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
                is_optional=False,
            )
        )

    # 2. Options facultatives souscrites (StudentOption)
    opt_stmt = (
        select(StudentOption)
        .join(Enrollment, StudentOption.enrollment_id == Enrollment.id)
        .where(Enrollment.student_id == student_id)
        .options(
            selectinload(StudentOption.optional_fee_option).selectinload(OptionalFeeOption.category),
        )
        .order_by(StudentOption.enrollment_id, StudentOption.id)
    )
    opt_rows = (await db.execute(opt_stmt)).scalars().all()

    for so in opt_rows:
        option = so.optional_fee_option
        category_name = option.category.name if option and option.category else "Inconnu"
        option_name = option.name if option else "Inconnu"
        amount = float(option.amount * so.quantity) if option else 0.0

        items.append(
            StudentEnrollmentFeeResponse(
                id=so.id,
                enrollment_id=so.enrollment_id,
                category_name=category_name,
                amount=amount,
                paid=0.0,  # Optional fees don't use EnrollmentFee/Payment
                remaining=amount,
                status="pending",
                is_optional=True,
                option_name=option_name,
            )
        )

    return StudentEnrollmentFeeListResponse(items=items)


# ---------------------------------------------------------------------------
# User account update
# ---------------------------------------------------------------------------


async def update_user_account(
    db: AsyncSession,
    user_id: int,
    *,
    email: str | None = None,
    password: str | None = None,
    updated_by: int,
) -> dict:
    """Met à jour l'email et/ou le mot de passe d'un compte utilisateur."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    old_values = {"email": user.email}

    if email is not None:
        # Vérifier unicité
        dup_stmt = select(User.id).where(User.email == email, User.id != user_id)
        dup = (await db.execute(dup_stmt)).scalar_one_or_none()
        if dup is not None:
            raise BusinessValidationError(f"L'email {email} est déjà utilisé par un autre compte")
        user.email = email

    if password is not None:
        user.hashed_password = hash_password(password)

    user.is_active = True

    await audit_log(
        db,
        entity_type="user",
        action=AuditAction.UPDATE,
        user_id=updated_by,
        entity_id=user_id,
        old_values=old_values,
        new_values={"email": email} if email else {},
    )

    await db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
    }


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


def _series_to_response(s: object) -> SeriesResponse:
    level_name = None
    if hasattr(s, "level") and s.level is not None:
        level_name = s.level.name
    return SeriesResponse(
        id=s.id,
        level_id=s.level_id,
        name=s.name,
        level_name=level_name,
    )


async def list_series(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
) -> SeriesListResponse:
    items, total = await repo.list_series(db, page=page, size=size, level_id=level_id)
    return SeriesListResponse(
        items=[_series_to_response(s) for s in items],
        total=total,
        page=page,
        size=size,
    )


async def get_series(db: AsyncSession, series_id: int) -> SeriesResponse:
    series = await repo.get_series_by_id(db, series_id)
    if series is None:
        raise NotFoundError("Series", series_id)
    return _series_to_response(series)


async def create_series(
    db: AsyncSession, data: SeriesCreate, *, created_by: int
) -> SeriesResponse:
    async with db.begin_nested():
        series = await repo.create_series(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="series",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=series.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_series_by_id(db, series.id)
    if refreshed is None:
        raise NotFoundError("Series", series.id)
    return _series_to_response(refreshed)


async def update_series(
    db: AsyncSession, series_id: int, data: SeriesUpdate, *, updated_by: int
) -> SeriesResponse:
    series = await repo.get_series_by_id(db, series_id)
    if series is None:
        raise NotFoundError("Series", series_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _series_to_response(series)
    async with db.begin_nested():
        await repo.update_series(db, series, **changes)
        await audit_log(
            db,
            entity_type="series",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=series_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_series_by_id(db, series_id)
    if refreshed is None:
        raise NotFoundError("Series", series_id)
    return _series_to_response(refreshed)


async def delete_series(
    db: AsyncSession, series_id: int, *, deleted_by: int
) -> None:
    series = await repo.get_series_by_id(db, series_id)
    if series is None:
        raise NotFoundError("Series", series_id)
    async with db.begin_nested():
        await repo.delete_series(db, series)
        await audit_log(
            db,
            entity_type="series",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=series_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------


def _role_to_response(r: object) -> RoleResponse:
    permissions = []
    if hasattr(r, "permissions"):
        for rp in r.permissions:
            if hasattr(rp, "permission") and rp.permission is not None:
                permissions.append(PermissionResponse.model_validate(rp.permission))
    return RoleResponse(
        id=r.id,
        name=r.name,
        description=r.description,
        permissions=permissions,
    )


async def list_roles(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> RoleListResponse:
    items, total = await repo.list_roles(db, page=page, size=size)
    return RoleListResponse(
        items=[_role_to_response(r) for r in items],
        total=total,
        page=page,
        size=size,
    )


async def get_role(db: AsyncSession, role_id: int) -> RoleResponse:
    role = await repo.get_role_by_id(db, role_id)
    if role is None:
        raise NotFoundError("Role", role_id)
    return _role_to_response(role)


async def create_role(
    db: AsyncSession, data: RoleCreate, *, created_by: int
) -> RoleResponse:
    async with db.begin_nested():
        role = await repo.create_role(db, name=data.name, description=data.description)
        if data.permission_ids:
            await repo.set_role_permissions(db, role.id, data.permission_ids)
        await audit_log(
            db,
            entity_type="role",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=role.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_role_by_id(db, role.id)
    if refreshed is None:
        raise NotFoundError("Role", role.id)
    return _role_to_response(refreshed)


async def update_role(
    db: AsyncSession, role_id: int, data: RoleUpdate, *, updated_by: int
) -> RoleResponse:
    role = await repo.get_role_by_id(db, role_id)
    if role is None:
        raise NotFoundError("Role", role_id)

    field_changes = data.model_dump(exclude={"permission_ids"}, exclude_none=True, mode="json")
    has_perm_change = data.permission_ids is not None

    if not field_changes and not has_perm_change:
        return _role_to_response(role)

    async with db.begin_nested():
        if field_changes:
            await repo.update_role(db, role, **field_changes)
        if has_perm_change:
            await repo.set_role_permissions(db, role_id, data.permission_ids)
        await audit_log(
            db,
            entity_type="role",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=role_id,
            new_values=data.model_dump(exclude_none=True, mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_role_by_id(db, role_id)
    if refreshed is None:
        raise NotFoundError("Role", role_id)
    return _role_to_response(refreshed)


async def delete_role(
    db: AsyncSession, role_id: int, *, deleted_by: int
) -> None:
    role = await repo.get_role_by_id(db, role_id)
    if role is None:
        raise NotFoundError("Role", role_id)
    async with db.begin_nested():
        await repo.delete_role(db, role)
        await audit_log(
            db,
            entity_type="role",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=role_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


async def list_permissions(db: AsyncSession) -> list[PermissionResponse]:
    items = await repo.list_permissions(db)
    return [PermissionResponse.model_validate(p) for p in items]


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


def _room_to_response(room: object) -> RoomResponse:
    r = RoomResponse.model_validate(room)
    # Attach the first class name and id if room has a class assigned
    if hasattr(room, "classes") and room.classes:  # type: ignore[union-attr]
        r.class_name = room.classes[0].name  # type: ignore[union-attr]
        r.class_id = room.classes[0].id  # type: ignore[union-attr]
    return r


async def list_rooms(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    room_type: str | None = None,
    search: str | None = None,
) -> RoomListResponse:
    rooms, total = await repo.list_rooms(
        db, page=page, size=size, room_type=room_type, search=search,
    )
    return RoomListResponse(
        items=[_room_to_response(r) for r in rooms],
        total=total,
        page=page,
        size=size,
    )


async def get_room(db: AsyncSession, room_id: int) -> RoomResponse:
    room = await repo.get_room_by_id(db, room_id)
    if not room:
        raise NotFoundError("Room", room_id)
    return _room_to_response(room)


async def create_room(
    db: AsyncSession, data: RoomCreate, *, created_by: int | None = None
) -> RoomResponse:
    room = await repo.create_room(
        db, name=data.name, capacity=data.capacity, room_type=data.room_type,
    )
    # Link room to class if class_id provided + sync capacity
    if data.class_id:
        cls = await repo.get_class_by_id(db, data.class_id)
        if cls:
            await repo.update_class(db, cls, room_id=room.id)
            if data.capacity is None and cls.max_students:
                await repo.update_room(db, room, capacity=cls.max_students)
    await audit_log(
        db,
        entity_type="room",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=room.id,
        new_values=data.model_dump(),
    )
    await db.commit()
    await db.refresh(room, ["classes"])
    return _room_to_response(room)


async def update_room(
    db: AsyncSession, room_id: int, data: RoomUpdate, *, updated_by: int | None = None
) -> RoomResponse:
    room = await repo.get_room_by_id(db, room_id)
    if not room:
        raise NotFoundError("Room", room_id)
    updates = data.model_dump(exclude_unset=True)
    # Handle class_id separately (it's on the Class model, not Room)
    has_class_id = "class_id" in updates
    class_id = updates.pop("class_id", None)
    if has_class_id:
        # Unlink old class(es) first
        if room.classes:
            for old_cls in room.classes:
                await repo.update_class(db, old_cls, room_id=None)
        # Link new class if provided
        if class_id:
            cls = await repo.get_class_by_id(db, class_id)
            if cls:
                await repo.update_class(db, cls, room_id=room.id)
    if updates:
        old_values = {k: getattr(room, k) for k in updates}
        room = await repo.update_room(db, room, **updates)
        await audit_log(
            db,
            entity_type="room",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=room_id,
            old_values=old_values,
            new_values=updates,
        )
    await db.commit()
    await db.refresh(room, ["classes"])
    return _room_to_response(room)


async def delete_room(
    db: AsyncSession, room_id: int, *, deleted_by: int | None = None
) -> None:
    room = await repo.get_room_by_id(db, room_id)
    if not room:
        raise NotFoundError("Room", room_id)
    await repo.delete_room(db, room)
    await audit_log(
        db,
        entity_type="room",
        action=AuditAction.DELETE,
        user_id=deleted_by,
        entity_id=room_id,
    )
    await db.commit()


async def batch_create_rooms_for_classes(
    db: AsyncSession, *, created_by: int | None = None
) -> RoomBatchCreateResponse:
    """Crée une salle pour chaque classe qui n'en a pas encore."""
    from app.models.academic import Class as ClassModel, Room as RoomModel

    # Get all classes without a room
    stmt = select(ClassModel).where(ClassModel.room_id.is_(None))
    classes_without_room = list((await db.execute(stmt)).scalars().all())

    # Get existing room names to avoid duplicates
    existing_names_stmt = select(RoomModel.name)
    existing_names = set((await db.execute(existing_names_stmt)).scalars().all())

    for cls in classes_without_room:
        room_name = f"Salle {cls.name}"
        if room_name in existing_names:
            room_name = f"Salle {cls.name} ({cls.id})"
        existing_names.add(room_name)

        room = await repo.create_room(
            db,
            name=room_name,
            capacity=cls.max_students,
            room_type="classroom",
        )
        await repo.update_class(db, cls, room_id=room.id)
        await audit_log(
            db,
            entity_type="room",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=room.id,
            new_values={"name": room_name, "class_id": cls.id, "batch": True},
        )

    await db.commit()

    # Re-fetch rooms for response
    rooms_final, _ = await repo.list_rooms(db, page=1, size=100)
    return RoomBatchCreateResponse(
        created=len(classes_without_room),
        rooms=[_room_to_response(r) for r in rooms_final],
    )
