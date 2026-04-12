"""Repository admin — accès DB pour les entités de base (CRUD)."""

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear, Class, Level, Series, Subject
from app.models.permission import Permission, Role, RolePermission
from app.models.user import StaffProfile, Student, TeacherProfile


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


async def get_student_by_id(db: AsyncSession, student_id: int) -> Student | None:
    stmt = select(Student).where(Student.id == student_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_students(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> tuple[list[Student], int]:
    base = select(Student)
    if search:
        pattern = f"%{search}%"
        base = base.where(
            Student.first_name.ilike(pattern) | Student.last_name.ilike(pattern)
        )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(Student.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_student(db: AsyncSession, **kwargs: object) -> Student:
    student = Student(**kwargs)
    db.add(student)
    await db.flush()
    return student


async def update_student(
    db: AsyncSession, student: Student, **kwargs: object
) -> Student:
    for key, value in kwargs.items():
        if value is not None:
            setattr(student, key, value)
    await db.flush()
    return student


async def delete_student(db: AsyncSession, student: Student) -> None:
    await db.delete(student)
    await db.flush()


# ---------------------------------------------------------------------------
# TeacherProfile
# ---------------------------------------------------------------------------


async def get_teacher_by_id(db: AsyncSession, teacher_id: int) -> TeacherProfile | None:
    stmt = select(TeacherProfile).where(TeacherProfile.id == teacher_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_teachers(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> tuple[list[TeacherProfile], int]:
    base = select(TeacherProfile)
    if search:
        pattern = f"%{search}%"
        base = base.where(
            TeacherProfile.first_name.ilike(pattern)
            | TeacherProfile.last_name.ilike(pattern)
        )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(TeacherProfile.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_teacher(db: AsyncSession, **kwargs: object) -> TeacherProfile:
    teacher = TeacherProfile(**kwargs)
    db.add(teacher)
    await db.flush()
    return teacher


async def update_teacher(
    db: AsyncSession, teacher: TeacherProfile, **kwargs: object
) -> TeacherProfile:
    for key, value in kwargs.items():
        if value is not None:
            setattr(teacher, key, value)
    await db.flush()
    return teacher


async def delete_teacher(db: AsyncSession, teacher: TeacherProfile) -> None:
    await db.delete(teacher)
    await db.flush()


# ---------------------------------------------------------------------------
# StaffProfile
# ---------------------------------------------------------------------------


async def get_staff_by_id(db: AsyncSession, staff_id: int) -> StaffProfile | None:
    stmt = select(StaffProfile).where(StaffProfile.id == staff_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_staff(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> tuple[list[StaffProfile], int]:
    base = select(StaffProfile)
    if search:
        pattern = f"%{search}%"
        base = base.where(
            StaffProfile.first_name.ilike(pattern)
            | StaffProfile.last_name.ilike(pattern)
        )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(StaffProfile.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_staff(db: AsyncSession, **kwargs: object) -> StaffProfile:
    staff = StaffProfile(**kwargs)
    db.add(staff)
    await db.flush()
    return staff


async def update_staff(
    db: AsyncSession, staff: StaffProfile, **kwargs: object
) -> StaffProfile:
    for key, value in kwargs.items():
        if value is not None:
            setattr(staff, key, value)
    await db.flush()
    return staff


async def delete_staff(db: AsyncSession, staff: StaffProfile) -> None:
    await db.delete(staff)
    await db.flush()


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


async def get_class_by_id(db: AsyncSession, class_id: int) -> Class | None:
    stmt = (
        select(Class)
        .options(
            selectinload(Class.level),
            selectinload(Class.series),
            selectinload(Class.academic_year),
        )
        .where(Class.id == class_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_classes(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
    academic_year_id: int | None = None,
) -> tuple[list[Class], int]:
    base = select(Class)
    if level_id is not None:
        base = base.where(Class.level_id == level_id)
    if academic_year_id is not None:
        base = base.where(Class.academic_year_id == academic_year_id)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        base.options(
            selectinload(Class.level),
            selectinload(Class.series),
            selectinload(Class.academic_year),
        )
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Class.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_class(db: AsyncSession, **kwargs: object) -> Class:
    cls = Class(**kwargs)
    db.add(cls)
    await db.flush()
    return cls


async def update_class(db: AsyncSession, cls: Class, **kwargs: object) -> Class:
    for key, value in kwargs.items():
        if value is not None:
            setattr(cls, key, value)
    await db.flush()
    return cls


async def delete_class(db: AsyncSession, cls: Class) -> None:
    await db.delete(cls)
    await db.flush()


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


async def get_subject_by_id(db: AsyncSession, subject_id: int) -> Subject | None:
    stmt = select(Subject).where(Subject.id == subject_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_subjects(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
) -> tuple[list[Subject], int]:
    base = select(Subject)
    if level_id is not None:
        base = base.where(Subject.level_id == level_id)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(Subject.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_subject(db: AsyncSession, **kwargs: object) -> Subject:
    subject = Subject(**kwargs)
    db.add(subject)
    await db.flush()
    return subject


async def update_subject(
    db: AsyncSession, subject: Subject, **kwargs: object
) -> Subject:
    for key, value in kwargs.items():
        if value is not None:
            setattr(subject, key, value)
    await db.flush()
    return subject


async def delete_subject(db: AsyncSession, subject: Subject) -> None:
    await db.delete(subject)
    await db.flush()


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


async def get_academic_year_by_id(
    db: AsyncSession, year_id: int
) -> AcademicYear | None:
    stmt = select(AcademicYear).where(AcademicYear.id == year_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_academic_years(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[list[AcademicYear], int]:
    base = select(AcademicYear)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(AcademicYear.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_academic_year(db: AsyncSession, **kwargs: object) -> AcademicYear:
    year = AcademicYear(**kwargs)
    db.add(year)
    await db.flush()
    return year


async def update_academic_year(
    db: AsyncSession, year: AcademicYear, **kwargs: object
) -> AcademicYear:
    for key, value in kwargs.items():
        if value is not None:
            setattr(year, key, value)
    await db.flush()
    return year


async def delete_academic_year(db: AsyncSession, year: AcademicYear) -> None:
    await db.delete(year)
    await db.flush()


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------


async def get_level_by_id(db: AsyncSession, level_id: int) -> Level | None:
    stmt = select(Level).where(Level.id == level_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_levels(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Level], int]:
    base = select(Level)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(Level.order.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_level(db: AsyncSession, **kwargs: object) -> Level:
    level = Level(**kwargs)
    db.add(level)
    await db.flush()
    return level


async def update_level(db: AsyncSession, level: Level, **kwargs: object) -> Level:
    for key, value in kwargs.items():
        if value is not None:
            setattr(level, key, value)
    await db.flush()
    return level


async def delete_level(db: AsyncSession, level: Level) -> None:
    await db.delete(level)
    await db.flush()


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


async def get_series_by_id(db: AsyncSession, series_id: int) -> Series | None:
    stmt = select(Series).options(selectinload(Series.level)).where(Series.id == series_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_series(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
) -> tuple[list[Series], int]:
    base = select(Series)
    if level_id is not None:
        base = base.where(Series.level_id == level_id)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.options(selectinload(Series.level)).offset((page - 1) * size).limit(size).order_by(Series.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_series(db: AsyncSession, **kwargs: object) -> Series:
    series = Series(**kwargs)
    db.add(series)
    await db.flush()
    return series


async def update_series(db: AsyncSession, series: Series, **kwargs: object) -> Series:
    for key, value in kwargs.items():
        if value is not None:
            setattr(series, key, value)
    await db.flush()
    return series


async def delete_series(db: AsyncSession, series: Series) -> None:
    await db.delete(series)
    await db.flush()


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------


async def get_role_by_id(db: AsyncSession, role_id: int) -> Role | None:
    stmt = (
        select(Role)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .where(Role.id == role_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_roles(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Role], int]:
    base = select(Role)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        base.options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Role.id.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_role(db: AsyncSession, name: str, description: str | None = None) -> Role:
    role = Role(name=name, description=description)
    db.add(role)
    await db.flush()
    return role


async def update_role(db: AsyncSession, role: Role, **kwargs: object) -> Role:
    for key, value in kwargs.items():
        if value is not None:
            setattr(role, key, value)
    await db.flush()
    return role


async def set_role_permissions(db: AsyncSession, role_id: int, permission_ids: list[int]) -> None:
    """Replace all permissions for a role."""
    await db.execute(sa_delete(RolePermission).where(RolePermission.role_id == role_id))
    for pid in permission_ids:
        db.add(RolePermission(role_id=role_id, permission_id=pid))
    await db.flush()


async def delete_role(db: AsyncSession, role: Role) -> None:
    await db.delete(role)
    await db.flush()


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


async def list_permissions(db: AsyncSession) -> list[Permission]:
    stmt = select(Permission).order_by(Permission.slug.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
