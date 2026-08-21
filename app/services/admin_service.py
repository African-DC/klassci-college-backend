"""Service admin — logique métier CRUD pour les entités de base."""

import asyncio
import logging
from typing import Any, Final

from fastapi import HTTPException
from sqlalchemy import case, func, select, text, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.security import hash_password
from app.models.academic import AcademicYear, SchoolHoliday, SchoolSettings, Trimester
from app.models.permission import UserRole
from app.models.user import (
    Parent,
    ParentStudent,
    StaffProfile,
    Student,
    TeacherProfile,
    User,
    UserRoleEnum,
)
from app.repositories import admin_repository as repo
from app.repositories import student_purge_repository as purge_repo
from app.schemas.admin import (
    AcademicYearCreate,
    AcademicYearListResponse,
    AcademicYearResponse,
    AcademicYearUpdate,
    AdminSummaryResponse,
    ClassCreate,
    ClassListResponse,
    ClassResponse,
    ClassUpdate,
    CurrentEnrollmentInfo,
    EnrollmentPatternUpdate,
    LevelCreate,
    LevelListResponse,
    LevelResponse,
    LevelUpdate,
    ParentCreate,
    ParentListResponse,
    ParentResponse,
    ParentUpdate,
    PermissionResponse,
    RoleCreate,
    RoleListResponse,
    RoleResponse,
    RoleUpdate,
    RoomBatchCreateResponse,
    RoomCreate,
    RoomListResponse,
    RoomResponse,
    RoomUpdate,
    SchoolInfoUpdate,
    SeriesCreate,
    SeriesListResponse,
    SeriesResponse,
    SeriesUpdate,
    StaffCreate,
    StaffListResponse,
    StaffResponse,
    StaffUpdate,
    StudentClassFilterCount,
    StudentCreate,
    StudentEnrollmentFeeListResponse,
    StudentEnrollmentFeeResponse,
    StudentFiltersResponse,
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
)
from app.services import archive_service, fees_paid
from app.services.finance_visibility import FinanceView, payment_pulse, redact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


def _student_to_response(s: object) -> StudentResponse:
    """Convertit un Student ORM en StudentResponse, en attachant l'inscription courante.

    `s.enrollments` est déjà borné par `with_loader_criteria` à l'année courante +
    status=valide côté repo, donc au plus 1 entrée. None si non inscrit.
    """
    response = StudentResponse.model_validate(s)
    enrollments = getattr(s, "enrollments", None) or []
    if enrollments:
        e = enrollments[0]
        response.current_enrollment = CurrentEnrollmentInfo(
            enrollment_id=e.id,
            class_id=e.class_id,
            class_name=e.class_.name if e.class_ else "",
            status=e.status,
        )
    return response


async def list_students(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    class_id: int | None = None,
    unenrolled_only: bool = False,
) -> StudentListResponse:
    if class_id is not None and unenrolled_only:
        raise BusinessValidationError(
            "Précisez soit class_id soit unenrolled_only, pas les deux.",
        )
    students, total = await repo.list_students(
        db,
        page=page,
        size=size,
        search=search,
        class_id=class_id,
        unenrolled_only=unenrolled_only,
    )
    return StudentListResponse(
        items=[_student_to_response(s) for s in students],
        total=total,
        page=page,
        size=size,
    )


async def get_admin_summary(db: AsyncSession) -> AdminSummaryResponse:
    """Agrégats KPI (classes, acteurs, salles, matières, inscriptions).

    Délègue le calcul SQL au repo ; le dict retourné mappe 1:1 le schéma.
    """
    data = await repo.get_admin_summary(db)
    return AdminSummaryResponse(**data)


async def get_students_filters(db: AsyncSession) -> StudentFiltersResponse:
    """Counts pour les chips : total, par classe, sans inscription année courante."""
    data = await repo.get_students_filters(db)
    return StudentFiltersResponse(
        total=data["total"],
        by_class=[
            StudentClassFilterCount(
                class_id=row["class_id"],
                class_name=row["class_name"],
                count=row["count"],
            )
            for row in data["by_class"]
        ],
        no_current_enrollment_count=data["no_current_enrollment_count"],
        current_academic_year_id=data["current_academic_year_id"],
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
        await _ensure_default_user_role(db, user.id, "student")

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


# ---------------------------------------------------------------------------
# Corbeille — les fiches personnes, toutes sur la même mécanique
# ---------------------------------------------------------------------------

TEACHER_KIND = archive_service.ArchivableKind(
    "teacher",
    "L'enseignant",
    TeacherProfile,
    lambda db, r: repo.delete_teacher(db, r),
    archive_service.owns_user_account,
)
STAFF_KIND = archive_service.ArchivableKind(
    "staff",
    "Le membre du personnel",
    StaffProfile,
    lambda db, r: repo.delete_staff(db, r),
    archive_service.owns_user_account,
)
PARENT_KIND = archive_service.ArchivableKind(
    "parent",
    "Le parent",
    Parent,
    lambda db, r: repo.delete_parent(db, r),
    archive_service.owns_user_account,
)
STUDENT_KIND = archive_service.ArchivableKind(
    "student",
    "L'eleve",
    Student,
    # Surtout pas `repo.delete_student`, qui est un `db.delete` nu : il ferait
    # sauter le RESTRICT sur `payments.enrollment_id`. L'argent encaissé
    # survit à la fiche de l'élève, sous identité figée.
    purge_repo.purge_student_keeping_payments,
    archive_service.owns_user_account,
    load=repo.get_archived_student_by_id,
    # Figer l'identité sur les versements AVANT que la fiche ne quitte les
    # écrans : le filtre qui masque l'élève archivé le masque aussi derrière
    # ses versements, et la colonne « Élève » du bordereau journalier se
    # viderait du jour au lendemain.
    before_archive=purge_repo.freeze_student_identity_on_payments,
)


async def _mandatory_expected_and_paid(
    db: AsyncSession, enrollment_id: int | None
) -> tuple[float, float]:
    """Ce qui est dû et ce qui a été versé sur une inscription, même périmètre.

    Les deux moitiés viennent du même endroit et couvrent les mêmes frais :
    obligatoires, exonérations exclues. Les calculer séparément est ce qui
    avait produit une fiche parent où le solde dû et le badge « à jour » se
    contredisaient — le badge suivait l'échéancier, qui exclut les frais
    exonérés, le solde non.
    """
    if enrollment_id is None:
        return 0.0, 0.0
    from app.repositories import installment_repository as installment_repo

    expected = await installment_repo.mandatory_total(db, enrollment_id)
    paid = await fees_paid.paid_on_mandatory(db, enrollment_id)
    return float(expected), float(paid)


async def get_student_full(db: AsyncSession, student_id: int, *, finance: FinanceView) -> dict:
    """Enriched student profile with user, enrollment, attendance, fees data.

    `finance` dit ce que l'appelant a le droit de lire des montants, et se
    passe toujours : un appel interne assume `FinanceView.INTERNAL` en toutes
    lettres plutôt que de l'obtenir en oubliant l'argument.
    """
    from app.models.attendance import AttendanceRecord
    from app.models.enrollment import Enrollment

    # Get student with user
    stmt = select(Student).where(Student.id == student_id).options(selectinload(Student.user))
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
        result["current_academic_year"] = (
            enrollment.academic_year.name if enrollment.academic_year else None
        )
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
        result["attendance_rate"] = (
            round((att_row.present or 0) / att_row.total * 100, 1) if att_row.total > 0 else 0.0
        )

    # Situation financière — même périmètre que le badge affiché juste en
    # dessous : frais obligatoires, exonérations déduites, année en cours.
    # Un solde calculé sur un autre périmètre que l'état de paiement produit
    # une fiche qui se contredit elle-même, « 80 000 restants » sous un badge
    # « à jour ».
    expected, paid = await _mandatory_expected_and_paid(db, enrollment.id if enrollment else None)

    result["fees_expected"] = expected
    result["fees_paid"] = paid
    result["fees_remaining"] = expected - paid
    result["fees_rate"] = round(paid / expected * 100, 1) if expected > 0 else 0.0

    if finance.status:
        result["fee_status"], result["last_payment_date"] = await payment_pulse(
            db, enrollment.id if enrollment else None
        )
    result = redact(result, finance)

    # Trimester breakdowns — alimentent les charts du tab Parcours.
    current_ay_id = enrollment.academic_year_id if enrollment else None
    grades, absences = await asyncio.gather(
        _student_trimester_grades(db, student_id=student_id, academic_year_id=current_ay_id),
        _student_trimester_absences(db, student_id=student_id, academic_year_id=current_ay_id),
    )
    result["trimester_grades"] = grades
    result["trimester_absences"] = absences

    return result


TRIMESTERS: Final[tuple[int, int, int]] = (1, 2, 3)


async def _student_trimester_grades(
    db: AsyncSession, *, student_id: int, academic_year_id: int | None
) -> list[dict]:
    """Moyenne générale + min/max matière par trimestre pour l'année courante."""
    if academic_year_id is None:
        return [{"trimester": t, "general": None, "best": None, "worst": None} for t in TRIMESTERS]

    from app.models.grade import Bulletin, SubjectAverage

    bulletin_stmt = select(Bulletin.trimester, Bulletin.average).where(
        Bulletin.student_id == student_id, Bulletin.academic_year_id == academic_year_id
    )
    sa_stmt = (
        select(
            SubjectAverage.trimester,
            func.min(SubjectAverage.average).label("worst"),
            func.max(SubjectAverage.average).label("best"),
        )
        .join(Bulletin, SubjectAverage.bulletin_id == Bulletin.id)
        .where(
            SubjectAverage.student_id == student_id,
            Bulletin.academic_year_id == academic_year_id,
        )
        .group_by(SubjectAverage.trimester)
    )
    bulletin_res, sa_res = await asyncio.gather(db.execute(bulletin_stmt), db.execute(sa_stmt))

    by_trim: dict[int, dict[str, float | None]] = {
        t: {"general": None, "best": None, "worst": None} for t in TRIMESTERS
    }
    for row in bulletin_res.all():
        if row.trimester in by_trim:
            by_trim[row.trimester]["general"] = (
                float(row.average) if row.average is not None else None
            )
    for row in sa_res.all():
        if row.trimester in by_trim:
            by_trim[row.trimester]["best"] = float(row.best) if row.best is not None else None
            by_trim[row.trimester]["worst"] = float(row.worst) if row.worst is not None else None

    return [{"trimester": t, **by_trim[t]} for t in TRIMESTERS]


async def _student_trimester_absences(
    db: AsyncSession, *, student_id: int, academic_year_id: int | None
) -> list[dict]:
    """Absences justifiées (EXCUSED) vs non justifiées (ABSENT) par trimestre.

    LATE n'est pas compté ici (ni absence ni justifié).
    """
    if academic_year_id is None:
        return [{"trimester": t, "justifiees": 0, "non_justifiees": 0} for t in TRIMESTERS]

    from app.models.academic import Trimester as TrimesterModel
    from app.models.attendance import AttendanceContext, AttendanceRecord, AttendanceStatus

    abs_stmt = (
        select(
            TrimesterModel.order_no.label("trimester"),
            func.sum(case((AttendanceRecord.status == AttendanceStatus.EXCUSED, 1), else_=0)).label(
                "justifiees"
            ),
            func.sum(case((AttendanceRecord.status == AttendanceStatus.ABSENT, 1), else_=0)).label(
                "non_justifiees"
            ),
        )
        .select_from(AttendanceRecord)
        .join(AttendanceContext, AttendanceRecord.context_id == AttendanceContext.id)
        .join(
            TrimesterModel,
            (TrimesterModel.academic_year_id == AttendanceContext.academic_year_id)
            & (AttendanceContext.date >= TrimesterModel.start_date)
            & (AttendanceContext.date <= TrimesterModel.end_date),
        )
        .where(
            AttendanceRecord.student_id == student_id,
            AttendanceContext.academic_year_id == academic_year_id,
            AttendanceRecord.status.in_([AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED]),
        )
        .group_by(TrimesterModel.order_no)
    )

    by_trim: dict[int, dict[str, int]] = {
        t: {"justifiees": 0, "non_justifiees": 0} for t in TRIMESTERS
    }
    for row in (await db.execute(abs_stmt)).all():
        if row.trimester in by_trim:
            by_trim[row.trimester]["justifiees"] = int(row.justifiees or 0)
            by_trim[row.trimester]["non_justifiees"] = int(row.non_justifiees or 0)

    return [{"trimester": t, **by_trim[t]} for t in TRIMESTERS]


async def create_student_user_account(
    db: AsyncSession, student_id: int, email: str, password: str, *, created_by: int
) -> dict:
    """Create a User account for an existing student without one."""
    student = await repo.get_student_by_id(db, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)
    if student.user_id is not None:
        raise HTTPException(status_code=400, detail="Cet élève a déjà un compte utilisateur")

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"L'email {email} est déjà utilisé")

    async with db.begin_nested():
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRoleEnum.STUDENT,
        )
        db.add(user)
        await db.flush()

        student.user_id = user.id
        await db.flush()

        from app.models.permission import Role
        from app.models.permission import UserRole as UserRoleModel

        role = (await db.execute(select(Role).where(Role.name == "student"))).scalar_one_or_none()
        if role:
            db.add(UserRoleModel(user_id=user.id, role_id=role.id))
            await db.flush()

        await audit_log(
            db,
            entity_type="student",
            action=AuditAction.UPDATE,
            user_id=created_by,
            entity_id=student_id,
            new_values={"user_id": user.id, "email": email},
        )
    await db.commit()
    return {"user_id": user.id, "email": email}


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


async def _ensure_default_user_role(db: AsyncSession, user_id: int, role_name: str) -> None:
    """Attache un user à son rôle par défaut dans user_roles (idempotent).

    Indispensable pour que les endpoints qui font `require_permission(slug)`
    voient les permissions héritées du rôle. Sans cet INSERT, l'utilisateur
    a son `users.role` enum (qui sert au portal routing JWT) mais aucune
    permission granulaire → 403 sur tout `/admin/*`.

    Voir [[feedback_user_roles_on_create]] et task #17.
    """
    role_id_row = await db.execute(
        text("SELECT id FROM roles WHERE name = :name"), {"name": role_name}
    )
    role_id = role_id_row.scalar_one_or_none()
    if role_id is None:
        logger.warning(
            "Role '%s' not seeded in tenant; user_id=%d created without user_roles entry",
            role_name,
            user_id,
        )
        return
    await db.execute(
        text("INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": user_id, "r": role_id},
    )


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
        await _ensure_default_user_role(db, user.id, "teacher")

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


async def get_teacher_full(db: AsyncSession, teacher_id: int) -> dict:
    """Enriched teacher profile with user account and aggregated KPIs."""
    from app.models.enrollment import Enrollment
    from app.models.grade import Evaluation
    from app.models.timetable import TimetableSlot
    from app.models.user import TeacherProfile

    # Get teacher with user
    stmt = (
        select(TeacherProfile)
        .where(TeacherProfile.id == teacher_id)
        .options(selectinload(TeacherProfile.user))
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
        "genre": teacher.genre,
        "contract_type": teacher.contract_type,
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
    classes_stmt = select(func.count(func.distinct(TimetableSlot.class_id))).where(
        TimetableSlot.teacher_id == teacher_id
    )

    # Count distinct students in those classes (via enrollments)
    students_stmt = (
        select(func.count(func.distinct(Enrollment.student_id)))
        .join(TimetableSlot, Enrollment.class_id == TimetableSlot.class_id)
        .where(TimetableSlot.teacher_id == teacher_id)
    )

    # Count evaluations
    evals_stmt = select(func.count()).where(Evaluation.teacher_id == teacher_id)

    classes_count = (await db.execute(classes_stmt)).scalar() or 0
    students_count = (await db.execute(students_stmt)).scalar() or 0
    evaluations_count = (await db.execute(evals_stmt)).scalar() or 0

    result["classes_count"] = classes_count
    result["students_count"] = students_count
    result["evaluations_count"] = evaluations_count

    # Hours per week (sum of subject hours_per_week via Subject assigned to teacher)
    from app.models.academic import Subject

    hours_stmt = select(func.coalesce(func.sum(Subject.hours_per_week), 0)).where(
        Subject.teacher_id == teacher_id
    )
    result["hours_per_week"] = float((await db.execute(hours_stmt)).scalar() or 0)

    # Availability rate
    from app.models.timetable import TeacherAvailability

    total_avail_stmt = (
        select(func.count())
        .select_from(TeacherAvailability)
        .where(TeacherAvailability.teacher_id == teacher_id)
    )
    available_stmt = (
        select(func.count())
        .select_from(TeacherAvailability)
        .where(
            TeacherAvailability.teacher_id == teacher_id,
            TeacherAvailability.available,
        )
    )
    total_avail = (await db.execute(total_avail_stmt)).scalar() or 0
    available_count = (await db.execute(available_stmt)).scalar() or 0

    # Availability rate — 3 cases :
    #  - "configured" : saisies présentes → rate = available / total
    #  - "implicit"  : pas de saisie mais slots EDT existants → rate proxy depuis
    #                  les slots (le prof EST par définition disponible quand il
    #                  est déjà affecté à un cours). Évite le faux "0% indispo
    #                  partout" alarmant pour un prof actif.
    #  - "none"      : aucune saisie ET aucun slot → "—" côté UI.
    #
    # MAX_SLOTS = 6 jours × 11 heures (cf. FE grid 7h–18h).
    MAX_SLOTS_PER_WEEK = 66
    if total_avail > 0:
        result["availability_rate"] = round(available_count / total_avail * 100, 1)
        result["availability_source"] = "configured"
    else:
        slots_count_stmt = (
            select(func.count())
            .select_from(TimetableSlot)
            .where(TimetableSlot.teacher_id == teacher_id)
        )
        slots_count = (await db.execute(slots_count_stmt)).scalar() or 0
        if slots_count > 0:
            result["availability_rate"] = round(min(slots_count / MAX_SLOTS_PER_WEEK * 100, 100), 1)
            result["availability_source"] = "implicit"
        else:
            result["availability_rate"] = 0
            result["availability_source"] = "none"

    # Include photo_url
    result["photo_url"] = teacher.photo_url

    # Detailed classes taught by this teacher in the current AY.
    # Aggregated from timetable_slots (the canonical source for the
    # teacher↔class relationship — there is no dedicated class_teachers
    # table). Each entry exposes the subjects taught in that class by this
    # teacher, the weekly hours invested, and the student count enrolled in
    # the current AY.
    from app.models.academic import Class as ClassModel
    from app.models.academic import Level
    from app.models.enrollment import EnrollmentStatus

    ay_id = await repo.get_current_academic_year_id(db)
    classes_detail: list[dict] = []
    if ay_id is not None:
        slot_rows_stmt = (
            select(
                ClassModel.id.label("class_id"),
                ClassModel.name.label("class_name"),
                Level.name.label("level_name"),
                Subject.name.label("subject_name"),
                TimetableSlot.start_time,
                TimetableSlot.end_time,
            )
            .select_from(TimetableSlot)
            .join(ClassModel, ClassModel.id == TimetableSlot.class_id)
            .outerjoin(Level, Level.id == ClassModel.level_id)
            .join(Subject, Subject.id == TimetableSlot.subject_id)
            .where(TimetableSlot.teacher_id == teacher_id)
            .where(TimetableSlot.academic_year_id == ay_id)
        )
        slot_rows = (await db.execute(slot_rows_stmt)).all()

        agg: dict[int, dict] = {}
        for row in slot_rows:
            entry = agg.setdefault(
                row.class_id,
                {
                    "id": row.class_id,
                    "name": row.class_name,
                    "level": row.level_name,
                    "subjects": set(),
                    "minutes": 0,
                },
            )
            entry["subjects"].add(row.subject_name)
            start_min = row.start_time.hour * 60 + row.start_time.minute
            end_min = row.end_time.hour * 60 + row.end_time.minute
            entry["minutes"] += max(0, end_min - start_min)

        for class_id, entry in agg.items():
            student_count = (
                await db.execute(
                    select(func.count(Enrollment.id))
                    .where(Enrollment.class_id == class_id)
                    .where(Enrollment.academic_year_id == ay_id)
                    .where(Enrollment.status == EnrollmentStatus.VALIDE)
                )
            ).scalar() or 0
            classes_detail.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "level": entry["level"],
                    "subjects": sorted(entry["subjects"]),
                    "hours_per_week": round(entry["minutes"] / 60, 1),
                    "student_count": int(student_count),
                }
            )

    classes_detail.sort(key=lambda c: c["name"])
    result["classes"] = classes_detail

    return result


# ---------------------------------------------------------------------------
# StaffProfile
# ---------------------------------------------------------------------------

# Rôles d'accès assignables à un membre du personnel. Volontairement restreint :
# jamais `admin` ni `super_admin` (pas d'escalade de privilèges via ce formulaire).
STAFF_ASSIGNABLE_ROLES: Final[tuple[str, ...]] = (
    "staff",
    "accountant",
    "cashier",
    "educator",
    "studies_director",
    "director",
)

# Ordre de seniorite utilise quand un compte porte plusieurs roles : on affiche
# le plus eleve. Doit couvrir tout STAFF_ASSIGNABLE_ROLES, sinon le rôle
# retombe sur un choix arbitraire (`next(iter(names))`).
_STAFF_ROLE_SENIORITY: Final[tuple[str, ...]] = (
    "director",
    "studies_director",
    "accountant",
    "cashier",
    "educator",
    "staff",
)


def _extract_staff_role(user: object | None) -> str | None:
    """Résout le rôle d'accès RBAC du staff depuis user.roles (selectinloaded)."""
    if user is None:
        return None
    roles = getattr(user, "roles", None) or []
    names = {ur.role.name for ur in roles if getattr(ur, "role", None) is not None}
    for preferred in _STAFF_ROLE_SENIORITY:
        if preferred in names:
            return preferred
    return next(iter(names), None)


async def _assert_staff_role_seeded(db: AsyncSession, role_name: str) -> None:
    """Refuse un rôle d'accès absent de la table `roles` de ce tenant.

    `_ensure_default_user_role` se contente d'un warning quand le rôle n'existe
    pas : acceptable pour le rôle implicite d'un élève, inacceptable ici. Le rôle
    a été choisi explicitement dans le formulaire ; l'ignorer créerait un compte
    sans aucune permission, qui se connecte puis se prend un 403 sur chaque page
    — avec un message « Créé avec succès » à l'écran.

    Cas réel : un tenant qui n'a pas encore joué la migration 0042 ne connaît pas
    `cashier` / `educator` / `studies_director`.
    """
    row = await db.execute(text("SELECT id FROM roles WHERE name = :name"), {"name": role_name})
    if row.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le rôle « {role_name} » n'est pas encore installé sur cet établissement. "
                "Mettez la base à jour avant de l'attribuer."
            ),
        )


def _validate_staff_role(role: str | None) -> str:
    """Valide le rôle demandé contre la whitelist, défaut `staff`."""
    if role is None or role == "":
        return "staff"
    if role not in STAFF_ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Rôle invalide. Valeurs autorisées : {', '.join(STAFF_ASSIGNABLE_ROLES)}",
        )
    return role


async def _set_staff_role(db: AsyncSession, user_id: int, role_name: str) -> None:
    """Remplace le rôle d'accès du staff (retire les anciens rôles staff, pose le nouveau)."""
    role_id = (
        await db.execute(text("SELECT id FROM roles WHERE name = :name"), {"name": role_name})
    ).scalar_one_or_none()
    if role_id is None:
        logger.warning("Role '%s' not seeded; user_id=%d role unchanged", role_name, user_id)
        return
    placeholders = ", ".join(f"'{r}'" for r in STAFF_ASSIGNABLE_ROLES)
    await db.execute(
        text(
            "DELETE FROM user_roles WHERE user_id = :u "
            f"AND role_id IN (SELECT id FROM roles WHERE name IN ({placeholders}))"
        ),
        {"u": user_id},
    )
    await db.execute(
        text("INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": user_id, "r": role_id},
    )
    # Le DELETE/INSERT ci-dessus passe par du SQL brut : l'ORM ignore la
    # mutation et garde en cache la collection `user.roles` deja chargee dans
    # cette session. Un `selectinload` ne reecrit pas une collection deja
    # peuplee, donc le refetch de `update_staff` renverrait l'ANCIEN role juste
    # apres l'avoir change — l'admin voit son changement rejete a l'ecran alors
    # que la base est correcte. On expire la collection pour forcer sa relecture.
    cached_user = await db.get(User, user_id)
    if cached_user is not None:
        db.expire(cached_user, ["roles"])


def _staff_to_response(s: object) -> StaffResponse:
    resp = StaffResponse.model_validate(s)
    resp.role = _extract_staff_role(getattr(s, "user", None))
    return resp


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


async def create_staff(db: AsyncSession, data: StaffCreate, *, created_by: int) -> StaffResponse:
    # Aligné sur create_teacher : un staff est avant tout un User auth-able,
    # le profil StaffProfile en est le contenu métier. On crée les deux en
    # une seule transaction pour éviter les comptes orphelins.
    existing = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"L'email {data.email} est déjà utilisé")

    role_name = _validate_staff_role(data.role)
    await _assert_staff_role_seeded(db, role_name)

    async with db.begin_nested():
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRoleEnum.STAFF,
        )
        db.add(user)
        await db.flush()
        await _ensure_default_user_role(db, user.id, role_name)

        profile_data = data.model_dump(exclude={"email", "password", "role"})
        profile_data["user_id"] = user.id
        staff = await repo.create_staff(db, **profile_data)
        await audit_log(
            db,
            entity_type="staff",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=staff.id,
            new_values={**data.model_dump(mode="json", exclude={"password"}), "user_id": user.id},
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
    # Le rôle d'accès n'est pas une colonne StaffProfile : on le traite à part.
    new_role = changes.pop("role", None)
    if new_role is not None:
        new_role = _validate_staff_role(new_role)
        await _assert_staff_role_seeded(db, new_role)
    if not changes and new_role is None:
        return _staff_to_response(staff)
    async with db.begin_nested():
        if changes:
            await repo.update_staff(db, staff, **changes)
        if new_role is not None and staff.user_id is not None:
            await _set_staff_role(db, staff.user_id, new_role)
        await audit_log(
            db,
            entity_type="staff",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=staff_id,
            new_values={**changes, **({"role": new_role} if new_role else {})},
        )
    await db.commit()
    refreshed = await repo.get_staff_by_id(db, staff_id)
    if refreshed is None:
        raise NotFoundError("Staff", staff_id)
    return _staff_to_response(refreshed)


async def get_staff_full(db: AsyncSession, staff_id: int) -> dict:
    """Enriched staff profile with user account info."""
    from app.models.user import StaffProfile

    stmt = (
        select(StaffProfile)
        .where(StaffProfile.id == staff_id)
        .options(
            selectinload(StaffProfile.user).selectinload(User.roles).selectinload(UserRole.role)
        )
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
        "role": _extract_staff_role(staff.user),
        "created_at": staff.created_at,
        "updated_at": staff.updated_at,
    }

    if staff.user:
        result["user_email"] = staff.user.email
        result["user_is_active"] = staff.user.is_active
        result["user_last_login"] = staff.user.last_login
        result["user_created_at"] = staff.user.created_at

    # Activité de l'année courante (versements encaissés, inscriptions traitées)
    from app.repositories import performance_repository as perf_repo

    ay = await perf_repo.get_current_year_with_calendar(db)
    activity: dict = {
        "payments_count": 0,
        "payments_amount": 0.0,
        "enrollments_count": 0,
        "academic_year_name": ay.name if ay else None,
    }
    if ay is not None and staff.user_id is not None:
        payments = await perf_repo.payment_activity_by_user(db, ay.start_date)
        enrollments = await perf_repo.enrollment_activity_by_user(db, ay.start_date)
        count, amount = payments.get(staff.user_id, (0, 0))
        activity["payments_count"] = count
        activity["payments_amount"] = float(amount)
        activity["enrollments_count"] = enrollments.get(staff.user_id, 0)
    result["activity"] = activity

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


async def _child_financial_context(
    db: AsyncSession,
    student_id: int,
    academic_year_id: int | None,
    *,
    finance: FinanceView,
) -> dict:
    """Classe + statut d'inscription + solde (frais) de l'élève pour l'AY courante.

    Un parent règle la scolarité de ses enfants : le solde par enfant est
    l'information la plus utile au secrétariat sur une fiche parent.
    """
    from app.models.enrollment import Enrollment

    ctx = {
        "class_name": None,
        "enrollment_status": None,
        "is_enrolled": False,
        "fees_expected": 0.0,
        "fees_paid": 0.0,
        "fees_balance": 0.0,
        "fee_status": None,
        "last_payment_date": None,
    }
    if academic_year_id is None:
        return ctx

    enr = (
        await db.execute(
            select(Enrollment)
            .where(
                Enrollment.student_id == student_id,
                Enrollment.academic_year_id == academic_year_id,
            )
            .options(selectinload(Enrollment.class_))
            .limit(1)
        )
    ).scalar_one_or_none()
    if enr is None:
        return ctx

    ctx["class_name"] = enr.class_.name if enr.class_ else None
    ctx["enrollment_status"] = enr.status
    ctx["is_enrolled"] = enr.status == "valide"

    expected, paid = await _mandatory_expected_and_paid(db, enr.id)
    ctx["fees_expected"] = expected
    ctx["fees_paid"] = paid
    ctx["fees_balance"] = expected - paid

    if finance.status:
        ctx["fee_status"], ctx["last_payment_date"] = await payment_pulse(db, enr.id)
    return ctx


async def get_parent_full(db: AsyncSession, parent_id: int, *, finance: FinanceView) -> dict:
    """Enriched parent profile with user account and children list.

    Chaque enfant est enrichi (classe, statut d'inscription, solde des frais)
    et un récapitulatif financier agrégé est calculé pour l'AY courante.
    """
    stmt = (
        select(Parent)
        .where(Parent.id == parent_id)
        .options(
            selectinload(Parent.user),
            selectinload(Parent.children).selectinload(ParentStudent.student),
        )
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
        "city": parent.city,
        "commune": parent.commune,
        "created_at": parent.created_at,
        "updated_at": parent.updated_at,
    }

    if parent.user:
        result["user_email"] = parent.user.email
        result["user_is_active"] = parent.user.is_active
        result["user_last_login"] = parent.user.last_login

    ay_id = await repo.get_current_academic_year_id(db)
    ay_name = await repo.get_current_academic_year_name(db)

    children = []
    total_expected = total_paid = 0.0
    enrolled_count = 0
    for link in parent.children:
        s = link.student
        ctx = await _child_financial_context(db, s.id, ay_id, finance=finance)
        children.append(
            {
                "student_id": s.id,
                "first_name": s.first_name,
                "last_name": s.last_name,
                "student_name": f"{s.first_name} {s.last_name}",
                "matricule": s.enrollment_number,
                "photo_url": s.photo_url,
                "relationship_type": link.relationship_type,
                **ctx,
            }
        )
        total_expected += ctx["fees_expected"]
        total_paid += ctx["fees_paid"]
        if ctx["is_enrolled"]:
            enrolled_count += 1
    # Redaction une seule fois, apres les totaux : le recapitulatif du foyer
    # se calcule sur les vraies valeurs, puis disparait avec elles.
    result["children"] = [redact(child, finance) for child in children]
    result["summary"] = {
        "children_count": len(children),
        "enrolled_count": enrolled_count,
        "total_expected": total_expected if finance.amounts else None,
        "total_paid": total_paid if finance.amounts else None,
        "total_balance": (total_expected - total_paid) if finance.amounts else None,
        "academic_year_name": ay_name,
    }

    return result


async def create_parent(db: AsyncSession, data: ParentCreate, *, created_by: int) -> ParentResponse:
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
            from app.models.permission import Role
            from app.models.permission import UserRole as UserRoleModel

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
        return {
            "parent_id": parent_id,
            "student_id": student_id,
            "relationship_type": relationship_type,
        }

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
    return {
        "parent_id": parent_id,
        "student_id": student_id,
        "relationship_type": relationship_type,
    }


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
    if hasattr(c, "level") and c.level is not None:
        level_name = c.level.name
    if hasattr(c, "series") and c.series is not None:
        series_name = c.series.name
    return ClassResponse(
        id=c.id,
        name=c.name,
        level_id=c.level_id,
        series_id=c.series_id,
        room_id=c.room_id,
        max_students=c.max_students,
        level_name=level_name,
        series_name=series_name,
        enrolled_count=enrolled_count,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _get_enrolled_counts(db: AsyncSession, class_ids: list[int]) -> dict[int, int]:
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
    search: str | None = None,
) -> ClassListResponse:
    classes, total = await repo.list_classes(
        db,
        page=page,
        size=size,
        level_id=level_id,
        search=search,
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


async def create_class(db: AsyncSession, data: ClassCreate, *, created_by: int) -> ClassResponse:
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


async def delete_class(db: AsyncSession, class_id: int, *, deleted_by: int) -> None:
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
    class_id: int | None = None,
    search: str | None = None,
) -> SubjectListResponse:
    if class_id is not None and level_id is not None:
        raise BusinessValidationError(
            "Précisez soit class_id soit level_id, pas les deux.",
        )
    subjects, total = await repo.list_subjects(
        db,
        page=page,
        size=size,
        level_id=level_id,
        class_id=class_id,
        search=search,
    )
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


async def delete_subject(db: AsyncSession, subject_id: int, *, deleted_by: int) -> None:
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


async def delete_academic_year(db: AsyncSession, year_id: int, *, deleted_by: int) -> None:
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
        stmt = update(AcademicYear).where(AcademicYear.id == year_id).values(is_current=True)
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


def _level_to_response(level: object) -> LevelResponse:
    return LevelResponse.model_validate(level)


async def list_levels(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> LevelListResponse:
    levels, total = await repo.list_levels(db, page=page, size=size)
    return LevelListResponse(
        items=[_level_to_response(level) for level in levels],
        total=total,
        page=page,
        size=size,
    )


async def get_level(db: AsyncSession, level_id: int) -> LevelResponse:
    level = await repo.get_level_by_id(db, level_id)
    if level is None:
        raise NotFoundError("Level", level_id)
    return _level_to_response(level)


async def create_level(db: AsyncSession, data: LevelCreate, *, created_by: int) -> LevelResponse:
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


async def delete_level(db: AsyncSession, level_id: int, *, deleted_by: int) -> None:
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
    """Get the school settings singleton.

    Lazily provisions a placeholder row on the first call so a fresh tenant
    can land on /admin/settings without a 404 — the admin then fills the
    real name/address/etc via the UI form.
    """
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    school = result.scalar_one_or_none()
    if school is None:
        school = SchoolSettings(school_name="Mon établissement")
        db.add(school)
        await db.flush()
        await db.commit()
    return school


async def get_trimesters_for_current_year(db: AsyncSession) -> list[Trimester]:
    """Retourne les trimestres de l'année académique courante (vide si aucune)."""
    year_id = await repo.get_current_academic_year_id(db)
    if year_id is None:
        return []
    stmt = (
        select(Trimester).where(Trimester.academic_year_id == year_id).order_by(Trimester.order_no)
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_notification_settings(
    db: AsyncSession, data: dict, *, updated_by: int
) -> SchoolSettings:
    """Met à jour les 7 préférences de notification du tenant."""
    school = await get_school_settings(db)
    fields = (
        "notify_by_email",
        "notify_by_sms",
        "notify_grades",
        "notify_absences",
        "notify_payments",
        "notify_enrollment",
        "notify_reenrollment",
    )
    async with db.begin_nested():
        for f in fields:
            if f in data:
                setattr(school, f, bool(data[f]))
        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            entity_id=school.id,
            action=AuditAction.UPDATE,
            user_id=updated_by,
            new_values={k: data.get(k) for k in fields if k in data},
        )
    await db.commit()
    return school


async def upsert_trimesters_for_current_year(
    db: AsyncSession, items: list[dict], *, updated_by: int
) -> list[Trimester]:
    """Remplace les trimestres de l'AY courante (delete + insert).

    Les items reçus suivent le format `{label, start_date, end_date}`.
    L'ordre est déterminé par l'index dans la liste (order_no = i + 1).
    """
    year_id = await repo.get_current_academic_year_id(db)
    if year_id is None:
        raise NotFoundError("AcademicYear", 0)

    async with db.begin_nested():
        await db.execute(sa_delete(Trimester).where(Trimester.academic_year_id == year_id))
        await db.flush()
        for i, item in enumerate(items, start=1):
            db.add(
                Trimester(
                    academic_year_id=year_id,
                    label=item["label"],
                    order_no=i,
                    start_date=item["start_date"],
                    end_date=item["end_date"],
                )
            )
        await db.flush()
        await audit_log(
            db,
            entity_type="trimesters",
            entity_id=year_id,
            action=AuditAction.UPDATE,
            user_id=updated_by,
            new_values={
                "items": [
                    {
                        "label": it["label"],
                        "start_date": str(it["start_date"]),
                        "end_date": str(it["end_date"]),
                    }
                    for it in items
                ]
            },
        )
    await db.commit()
    stmt = (
        select(Trimester).where(Trimester.academic_year_id == year_id).order_by(Trimester.order_no)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_holidays_for_current_year(db: AsyncSession) -> list[SchoolHoliday]:
    """Retourne les congés de l'année académique courante (vide si aucune)."""
    year_id = await repo.get_current_academic_year_id(db)
    if year_id is None:
        return []
    stmt = (
        select(SchoolHoliday)
        .where(SchoolHoliday.academic_year_id == year_id)
        .order_by(SchoolHoliday.start_date)
    )
    return list((await db.execute(stmt)).scalars().all())


async def upsert_holidays_for_current_year(
    db: AsyncSession, items: list[dict], *, updated_by: int
) -> list[SchoolHoliday]:
    """Remplace les congés de l'AY courante (delete + insert).

    Les items reçus suivent le format `{label, start_date, end_date}`.
    """
    year_id = await repo.get_current_academic_year_id(db)
    if year_id is None:
        raise NotFoundError("AcademicYear", 0)

    async with db.begin_nested():
        await db.execute(sa_delete(SchoolHoliday).where(SchoolHoliday.academic_year_id == year_id))
        await db.flush()
        for item in items:
            db.add(
                SchoolHoliday(
                    academic_year_id=year_id,
                    label=item["label"],
                    start_date=item["start_date"],
                    end_date=item["end_date"],
                )
            )
        await db.flush()
        await audit_log(
            db,
            entity_type="school_holidays",
            entity_id=year_id,
            action=AuditAction.UPDATE,
            user_id=updated_by,
            new_values={
                "items": [
                    {
                        "label": it["label"],
                        "start_date": str(it["start_date"]),
                        "end_date": str(it["end_date"]),
                    }
                    for it in items
                ]
            },
        )
    await db.commit()
    stmt = (
        select(SchoolHoliday)
        .where(SchoolHoliday.academic_year_id == year_id)
        .order_by(SchoolHoliday.start_date)
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_school_info(
    db: AsyncSession, data: SchoolInfoUpdate, *, updated_by: int
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


async def clear_school_signature(db: AsyncSession, *, updated_by: int) -> SchoolSettings:
    """Clear the school official signature URL (DELETE flow)."""
    school = await get_school_settings(db)
    if school.signature_image_url is None:
        return school
    async with db.begin_nested():
        school.signature_image_url = None
        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=school.id,
            new_values={"signature_image_url": None},
        )
    await db.commit()
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
    from app.models.fee import (
        EnrollmentFee,
        FeeVariant,
        OptionalFeeOption,
    )

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
        )
        .order_by(EnrollmentFee.enrollment_id, EnrollmentFee.id)
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Le calcul canonique, partagé avec les portails : un frais ne peut pas
    # valoir un montant côté administration et un autre côté famille.
    paid_by_fee = await fees_paid.paid_by_enrollment_fee(db, student_id)

    items: list[StudentEnrollmentFeeResponse] = []
    for ef in rows:
        category_name = (
            ef.fee_variant.category.name
            if ef.fee_variant and ef.fee_variant.category
            else "Inconnu"
        )
        paid = float(paid_by_fee.get(ef.id, 0))
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
            selectinload(StudentOption.optional_fee_option).selectinload(
                OptionalFeeOption.category
            ),
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


async def create_series(db: AsyncSession, data: SeriesCreate, *, created_by: int) -> SeriesResponse:
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


async def delete_series(db: AsyncSession, series_id: int, *, deleted_by: int) -> None:
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


async def create_role(db: AsyncSession, data: RoleCreate, *, created_by: int) -> RoleResponse:
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

    # Capture old permission_ids BEFORE the update so audit trail records the diff.
    old_perm_ids = sorted(rp.permission_id for rp in role.permissions) if has_perm_change else None

    async with db.begin_nested():
        if field_changes:
            await repo.update_role(db, role, **field_changes)
        if has_perm_change:
            await repo.set_role_permissions(db, role_id, data.permission_ids)
        old_values: dict[str, Any] | None = (
            {"permission_ids": old_perm_ids} if has_perm_change else None
        )
        new_values = data.model_dump(exclude_none=True, mode="json")
        if has_perm_change and "permission_ids" in new_values:
            new_values["permission_ids"] = sorted(new_values["permission_ids"])
        await audit_log(
            db,
            entity_type="role",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=role_id,
            old_values=old_values,
            new_values=new_values,
        )
    await db.commit()
    refreshed = await repo.get_role_by_id(db, role_id)
    if refreshed is None:
        raise NotFoundError("Role", role_id)
    return _role_to_response(refreshed)


async def delete_role(db: AsyncSession, role_id: int, *, deleted_by: int) -> None:
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
        db,
        page=page,
        size=size,
        room_type=room_type,
        search=search,
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
        db,
        name=data.name,
        capacity=data.capacity,
        room_type=data.room_type,
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
    fresh = await repo.get_room_by_id(db, room.id)
    assert fresh is not None
    return _room_to_response(fresh)


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


async def delete_room(db: AsyncSession, room_id: int, *, deleted_by: int | None = None) -> None:
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
    from app.models.academic import Class as ClassModel
    from app.models.academic import Room as RoomModel

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
