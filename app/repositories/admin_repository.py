"""Repository admin — accès DB pour les entités de base (CRUD)."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.models.academic import AcademicYear, Class, Level, Room, Series, Subject
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.permission import Permission, Role, RolePermission, UserRole
from app.models.user import Parent, ParentStudent, StaffProfile, Student, TeacherProfile, User
from app.utils.fuzzy_search import fuzzy_filter_by_name

# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


async def get_current_academic_year_id(db: AsyncSession) -> int | None:
    """Retourne l'id de l'année scolaire courante (`is_current = true`) ou None."""
    stmt = select(AcademicYear.id).where(AcademicYear.is_current.is_(True)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_current_academic_year_name(db: AsyncSession) -> str | None:
    """Retourne le label ("2025-2026") de l'année courante ou None."""
    stmt = select(AcademicYear.name).where(AcademicYear.is_current.is_(True)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def _student_with_current_enrollment_options(current_ay_id: int | None) -> list:
    """Loader options bornant `Student.enrollments` à l'année courante.

    Single source of truth partagée entre `list_students` et `get_student_by_id` :
    sans ce eager-load, `_student_to_response` plante avec `MissingGreenlet` quand
    il lit `s.enrollments` (lazy-load implicite hors greenlet async).
    """
    options: list = [selectinload(Student.enrollments).options(selectinload(Enrollment.class_))]
    if current_ay_id is not None:
        options.append(
            with_loader_criteria(
                Enrollment,
                Enrollment.academic_year_id == current_ay_id,
                include_aliases=True,
            )
        )
    return options


async def get_student_by_id(db: AsyncSession, student_id: int) -> Student | None:
    """Charge un Student avec son inscription année courante eager-loaded.

    Eager-load obligatoire : tous les callers passent par `_student_to_response`
    qui lit `s.enrollments` — sans options, MissingGreenlet → 500.
    """
    current_ay_id = await get_current_academic_year_id(db)
    stmt = (
        select(Student)
        .where(Student.id == student_id)
        .options(*_student_with_current_enrollment_options(current_ay_id))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_students(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    class_id: int | None = None,
    unenrolled_only: bool = False,
) -> tuple[list[Student], int]:
    """Liste paginée des élèves, enrichie de l'inscription année courante.

    Le `with_loader_criteria` borne les `Student.enrollments` chargés à l'année
    courante uniquement, status `valide`. Combiné à la `UniqueConstraint(student_id,
    academic_year_id)` sur `enrollments`, on a au plus une enrollment par élève
    après filtrage — pas besoin de window function ni de tri par updated_at.

    `class_id` filtre les élèves dont l'inscription courante est dans cette classe.
    `unenrolled_only` filtre les élèves SANS inscription valide cette année.
    Les deux filtres sont mutuellement exclusifs (422 levée côté service).
    """
    current_ay_id = await get_current_academic_year_id(db)

    base = select(Student)

    if search:
        words = search.strip().split()
        for word in words:
            pattern = f"%{word}%"
            base = base.where(
                or_(Student.first_name.ilike(pattern), Student.last_name.ilike(pattern))
            )

    # Class filter / unenrolled filter — both go through enrollments.
    if class_id is not None:
        # Élève qui a une enrollment valide dans la classe demandée pour l'année courante.
        if current_ay_id is None:
            return [], 0  # pas d'année courante → liste vide pour ce filtre
        base = base.where(
            Student.enrollments.any(
                and_(
                    Enrollment.academic_year_id == current_ay_id,
                    Enrollment.status == EnrollmentStatus.VALIDE,
                    Enrollment.class_id == class_id,
                )
            )
        )
    elif unenrolled_only:
        # Élève dont l'inscription n'est pas même entamée pour l'année
        # courante. Une inscription en cours de validation compte : elle a
        # été entamée, et la présenter comme « à inscrire » ferait recommencer
        # un dossier déjà ouvert.
        if current_ay_id is None:
            # Pas d'année courante → tous les élèves sont "non inscrits".
            pass
        else:
            base = base.where(
                ~Student.enrollments.any(Enrollment.academic_year_id == current_ay_id)
            )

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    options = _student_with_current_enrollment_options(current_ay_id)

    stmt = (
        base.options(*options)
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    # Fuzzy fallback: si ILIKE n'a rien trouvé, on tente une recherche floue
    # (sans les filtres class_id / unenrolled_only — c'est volontaire :
    # l'utilisateur cherche un élève par nom, pas par cohorte).
    if search and total == 0 and class_id is None and not unenrolled_only:
        all_stmt = select(Student).options(*options).order_by(Student.last_name.asc())
        all_rows = list((await db.execute(all_stmt)).scalars().all())
        fuzzy_results = fuzzy_filter_by_name(
            all_rows,
            search,
            name_getter=lambda s: f"{s.first_name} {s.last_name} {s.enrollment_number or ''}",
            limit=size,
        )
        return fuzzy_results, len(fuzzy_results)

    return rows, total


async def get_students_filters(db: AsyncSession) -> dict:
    """Compte les élèves par cohorte pour la barre de chips.

    Retourne `{ total, by_class: [...], no_current_enrollment_count }`.
    `by_class` ne liste que les classes ayant au moins 1 inscription valide
    cette année — pas la peine d'afficher les classes vides comme chip.
    """
    current_ay_id = await get_current_academic_year_id(db)

    total_stmt = select(func.count(Student.id))
    total: int = (await db.execute(total_stmt)).scalar() or 0

    by_class: list[dict] = []
    no_current = 0

    if current_ay_id is None:
        # Pas d'année courante → tout le monde est "non inscrit".
        return {
            "total": total,
            "by_class": [],
            "no_current_enrollment_count": total,
            "current_academic_year_id": None,
        }

    # Comptage par classe via JOIN avec enrollments valide année courante.
    by_class_stmt = (
        select(
            Class.id.label("class_id"),
            Class.name.label("class_name"),
            func.count(func.distinct(Enrollment.student_id)).label("count"),
        )
        .select_from(Enrollment)
        .join(Class, Enrollment.class_id == Class.id)
        .where(
            Enrollment.academic_year_id == current_ay_id,
            Enrollment.status == EnrollmentStatus.VALIDE,
        )
        .group_by(Class.id, Class.name)
        .order_by(Class.name.asc())
    )
    rows = (await db.execute(by_class_stmt)).all()
    by_class = [
        {"class_id": r.class_id, "class_name": r.class_name, "count": r.count} for r in rows
    ]

    # Élèves dont l'inscription n'est pas même entamée cette année. Le même
    # prédicat que la liste filtrée : les deux doivent compter la même chose,
    # sinon la pastille annonce huit élèves et la liste en montre trois.
    no_current_stmt = select(func.count(Student.id)).where(
        ~Student.enrollments.any(Enrollment.academic_year_id == current_ay_id)
    )
    no_current = (await db.execute(no_current_stmt)).scalar() or 0

    return {
        "total": total,
        "by_class": by_class,
        "no_current_enrollment_count": no_current,
        "current_academic_year_id": current_ay_id,
    }


_ACTIVE_ENROLLMENT = (
    EnrollmentStatus.PROSPECT,
    EnrollmentStatus.EN_VALIDATION,
    EnrollmentStatus.VALIDE,
)


def _nonempty(col: object) -> object:
    """Prédicat 'colonne texte renseignée' (non NULL et non vide)."""
    return and_(col.isnot(None), col != "")  # type: ignore[union-attr]


async def get_admin_summary(db: AsyncSession) -> dict:
    """Agrégats serveur pour les bandeaux KPI admin.

    Calculés en SQL (COUNT/SUM/GROUP BY) — corrects quelle que soit la
    volumétrie, contrairement à un comptage côté client borné par la
    pagination (`size<=100`).
    """

    async def _scalar(stmt: object) -> int:
        return int((await db.execute(stmt)).scalar() or 0)  # type: ignore[arg-type]

    # --- Classes : total, places, inscrits (statuts actifs), classes pleines ---
    enrolled_subq = (
        select(
            Enrollment.class_id.label("class_id"),
            func.count(Enrollment.id).label("ec"),
        )
        .where(Enrollment.status.in_(_ACTIVE_ENROLLMENT))
        .group_by(Enrollment.class_id)
        .subquery()
    )
    classes = {
        "total": await _scalar(select(func.count(Class.id))),
        "capacity": await _scalar(select(func.coalesce(func.sum(Class.max_students), 0))),
        "enrolled": await _scalar(
            select(func.count(Enrollment.id)).where(Enrollment.status.in_(_ACTIVE_ENROLLMENT))
        ),
        "full": await _scalar(
            select(func.count(Class.id))
            .select_from(Class)
            .join(enrolled_subq, enrolled_subq.c.class_id == Class.id)
            .where(
                Class.max_students > 0,
                enrolled_subq.c.ec > 0.95 * Class.max_students,
            )
        ),
    }

    # --- Enseignants ---
    teachers_total = await _scalar(select(func.count(TeacherProfile.id)))
    teachers_with_spec = await _scalar(
        select(func.count(TeacherProfile.id)).where(_nonempty(TeacherProfile.speciality))
    )
    teachers = {
        "total": teachers_total,
        "with_speciality": teachers_with_spec,
        "with_phone": await _scalar(
            select(func.count(TeacherProfile.id)).where(_nonempty(TeacherProfile.phone))
        ),
        "without_speciality": teachers_total - teachers_with_spec,
    }

    # --- Personnel ---
    staff_total = await _scalar(select(func.count(StaffProfile.id)))
    staff_with_position = await _scalar(
        select(func.count(StaffProfile.id)).where(_nonempty(StaffProfile.position))
    )
    staff = {
        "total": staff_total,
        "distinct_positions": await _scalar(
            select(func.count(func.distinct(StaffProfile.position))).where(
                _nonempty(StaffProfile.position)
            )
        ),
        "with_phone": await _scalar(
            select(func.count(StaffProfile.id)).where(_nonempty(StaffProfile.phone))
        ),
        "without_position": staff_total - staff_with_position,
    }

    # --- Parents ---
    parents_total = await _scalar(select(func.count(Parent.id)))
    parents_with_account = await _scalar(
        select(func.count(Parent.id)).where(Parent.user_id.isnot(None))
    )
    parents = {
        "total": parents_total,
        "with_account": parents_with_account,
        "with_email": await _scalar(select(func.count(Parent.id)).where(_nonempty(Parent.email))),
        "without_account": parents_total - parents_with_account,
    }

    # --- Salles ---
    rooms = {
        "total": await _scalar(select(func.count(Room.id))),
        "capacity": await _scalar(select(func.coalesce(func.sum(Room.capacity), 0))),
        "classrooms": await _scalar(
            select(func.count(Room.id)).where(Room.room_type == "classroom")
        ),
        "classes_without_room": await _scalar(
            select(func.count(Class.id)).where(Class.room_id.is_(None))
        ),
    }

    # --- Matières : catalogue (level_id NULL) vs instances (level_id renseigné) ---
    subjects = {
        "unique_names": await _scalar(select(func.count(func.distinct(Subject.name)))),
        "instances": await _scalar(
            select(func.count(Subject.id)).where(Subject.level_id.isnot(None))
        ),
        "without_teacher": await _scalar(
            select(func.count(Subject.id)).where(
                Subject.level_id.isnot(None), Subject.teacher_id.is_(None)
            )
        ),
        "total_hours": await _scalar(
            select(func.coalesce(func.sum(Subject.hours_per_week), 0)).where(
                Subject.level_id.isnot(None)
            )
        ),
    }

    # --- Inscriptions (toutes années, comme la liste paginée) ---
    enrollments = {
        "total": await _scalar(select(func.count(Enrollment.id))),
        "valid": await _scalar(
            select(func.count(Enrollment.id)).where(Enrollment.status == EnrollmentStatus.VALIDE)
        ),
        "pending": await _scalar(
            select(func.count(Enrollment.id)).where(
                Enrollment.status.in_((EnrollmentStatus.PROSPECT, EnrollmentStatus.EN_VALIDATION))
            )
        ),
        "closed": await _scalar(
            select(func.count(Enrollment.id)).where(
                Enrollment.status.in_((EnrollmentStatus.REJETE, EnrollmentStatus.ANNULE))
            )
        ),
    }

    return {
        "classes": classes,
        "teachers": teachers,
        "staff": staff,
        "parents": parents,
        "rooms": rooms,
        "subjects": subjects,
        "enrollments": enrollments,
    }


async def create_student(db: AsyncSession, **kwargs: object) -> Student:
    student = Student(**kwargs)
    db.add(student)
    await db.flush()
    return student


async def update_student(db: AsyncSession, student: Student, **kwargs: object) -> Student:
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
        words = search.strip().split()
        for word in words:
            pattern = f"%{word}%"
            base = base.where(
                or_(
                    TeacherProfile.first_name.ilike(pattern),
                    TeacherProfile.last_name.ilike(pattern),
                )
            )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(TeacherProfile.id.desc())
    rows = list((await db.execute(stmt)).scalars().all())

    if search and total == 0:
        all_stmt = select(TeacherProfile).order_by(TeacherProfile.id.desc())
        all_rows = list((await db.execute(all_stmt)).scalars().all())
        fuzzy_results = fuzzy_filter_by_name(
            all_rows,
            search,
            name_getter=lambda t: f"{t.first_name} {t.last_name}",
            limit=size,
        )
        return fuzzy_results, len(fuzzy_results)

    return rows, total


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


def _staff_role_load_options():
    """selectinload user + user_roles + role pour résoudre le rôle RBAC du staff
    sans MissingGreenlet lors de la sérialisation post-commit."""
    return selectinload(StaffProfile.user).selectinload(User.roles).selectinload(UserRole.role)


async def get_staff_by_id(db: AsyncSession, staff_id: int) -> StaffProfile | None:
    stmt = (
        select(StaffProfile).where(StaffProfile.id == staff_id).options(_staff_role_load_options())
    )
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
        words = search.strip().split()
        for word in words:
            pattern = f"%{word}%"
            base = base.where(
                or_(StaffProfile.first_name.ilike(pattern), StaffProfile.last_name.ilike(pattern))
            )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        base.options(_staff_role_load_options())
        .offset((page - 1) * size)
        .limit(size)
        .order_by(StaffProfile.id.desc())
    )
    rows = list((await db.execute(stmt)).scalars().all())

    if search and total == 0:
        all_stmt = (
            select(StaffProfile)
            .options(_staff_role_load_options())
            .order_by(StaffProfile.id.desc())
        )
        all_rows = list((await db.execute(all_stmt)).scalars().all())
        fuzzy_results = fuzzy_filter_by_name(
            all_rows,
            search,
            name_getter=lambda s: f"{s.first_name} {s.last_name}",
            limit=size,
        )
        return fuzzy_results, len(fuzzy_results)
    return list(rows), total


async def create_staff(db: AsyncSession, **kwargs: object) -> StaffProfile:
    staff = StaffProfile(**kwargs)
    db.add(staff)
    await db.flush()
    return staff


async def update_staff(db: AsyncSession, staff: StaffProfile, **kwargs: object) -> StaffProfile:
    for key, value in kwargs.items():
        if value is not None:
            setattr(staff, key, value)
    await db.flush()
    return staff


async def delete_staff(db: AsyncSession, staff: StaffProfile) -> None:
    await db.delete(staff)
    await db.flush()


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------


async def get_parent_by_id(db: AsyncSession, parent_id: int) -> Parent | None:
    stmt = select(Parent).where(Parent.id == parent_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_parents(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
) -> tuple[list[Parent], int]:
    base = select(Parent)
    if search:
        words = search.strip().split()
        for word in words:
            pattern = f"%{word}%"
            base = base.where(
                or_(Parent.first_name.ilike(pattern), Parent.last_name.ilike(pattern))
            )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(Parent.id.desc())
    rows = list((await db.execute(stmt)).scalars().all())

    if search and total == 0:
        all_stmt = select(Parent).order_by(Parent.id.desc())
        all_rows = list((await db.execute(all_stmt)).scalars().all())
        fuzzy_results = fuzzy_filter_by_name(
            all_rows,
            search,
            name_getter=lambda p: f"{p.first_name} {p.last_name}",
            limit=size,
        )
        return fuzzy_results, len(fuzzy_results)

    return rows, total


async def create_parent(db: AsyncSession, **kwargs: object) -> Parent:
    parent = Parent(**kwargs)
    db.add(parent)
    await db.flush()
    return parent


async def update_parent(db: AsyncSession, parent: Parent, **kwargs: object) -> Parent:
    for key, value in kwargs.items():
        if value is not None:
            setattr(parent, key, value)
    await db.flush()
    return parent


async def delete_parent(db: AsyncSession, parent: Parent) -> None:
    await db.delete(parent)
    await db.flush()


async def get_student_parents(db: AsyncSession, student_id: int) -> list[tuple[Parent, str]]:
    """Return list of (Parent, relationship_type) for a student."""
    stmt = (
        select(Parent, ParentStudent.relationship_type)
        .join(ParentStudent, Parent.id == ParentStudent.parent_id)
        .where(ParentStudent.student_id == student_id)
        .order_by(Parent.id.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


async def get_class_by_id(db: AsyncSession, class_id: int) -> Class | None:
    stmt = (
        select(Class)
        .options(
            selectinload(Class.level),
            selectinload(Class.series),
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
    search: str | None = None,
) -> tuple[list[Class], int]:
    base = select(Class)
    if level_id is not None:
        base = base.where(Class.level_id == level_id)
    if search:
        pattern = f"%{search}%"
        base = base.where(Class.name.ilike(pattern))
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    # Tri par ordre pédagogique naturel : 6ème → Terminale, puis A/B/C…
    # L'ancien tri `Class.id.desc()` exposait les classes en ordre de création,
    # ce qui plaçait Terminale en haut dans les dropdowns (Mme Diallo inscrit
    # majoritairement en 6ème à la rentrée — mauvais persona-fit). Bug #23.
    stmt = (
        base.outerjoin(Level, Class.level_id == Level.id)
        .options(
            selectinload(Class.level),
            selectinload(Class.series),
        )
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Level.order.asc(), Class.name.asc())
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
    stmt = (
        select(Subject)
        .options(
            selectinload(Subject.level), selectinload(Subject.series), selectinload(Subject.teacher)
        )
        .where(Subject.id == subject_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_subjects(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    level_id: int | None = None,
    class_id: int | None = None,
    search: str | None = None,
) -> tuple[list[Subject], int]:
    # `class_id` filtre les matières enseignées dans cette classe (level + series, avec
    # null-semantics) en réutilisant le prédicat partagé de curriculum_service.
    # `level_id` reste un filtre direct sur Subject.level_id, conservé pour la
    # rétrocompat. Les deux sont mutuellement exclusifs côté service (422).
    from app.models.academic import Class
    from app.services.curriculum_service import subject_for_class_predicate

    base = select(Subject)
    if class_id is not None:
        class_obj = await db.get(Class, class_id)
        if class_obj is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError("Class", class_id)
        base = base.where(subject_for_class_predicate(class_obj))
    elif level_id is not None:
        base = base.where(Subject.level_id == level_id)
    if search:
        pattern = f"%{search}%"
        base = base.where(Subject.name.ilike(pattern))
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        base.options(
            selectinload(Subject.level),
            selectinload(Subject.series),
            selectinload(Subject.teacher),
        )
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Subject.name.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_subject(db: AsyncSession, **kwargs: object) -> Subject:
    subject = Subject(**kwargs)
    db.add(subject)
    await db.flush()
    return subject


async def update_subject(db: AsyncSession, subject: Subject, **kwargs: object) -> Subject:
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


async def get_academic_year_by_id(db: AsyncSession, year_id: int) -> AcademicYear | None:
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
    stmt = (
        base.options(selectinload(Series.level))
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Series.id.desc())
    )
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


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


async def get_room_by_id(db: AsyncSession, room_id: int) -> Room | None:
    stmt = select(Room).options(selectinload(Room.classes)).where(Room.id == room_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_rooms(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    room_type: str | None = None,
    search: str | None = None,
) -> tuple[list[Room], int]:
    base = select(Room)
    if room_type is not None:
        base = base.where(Room.room_type == room_type)
    if search:
        pattern = f"%{search}%"
        base = base.where(Room.name.ilike(pattern))
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = (
        base.options(selectinload(Room.classes))
        .offset((page - 1) * size)
        .limit(size)
        .order_by(Room.name.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_room(db: AsyncSession, **kwargs: object) -> Room:
    room = Room(**kwargs)
    db.add(room)
    await db.flush()
    return room


async def update_room(db: AsyncSession, room: Room, **kwargs: object) -> Room:
    for key, value in kwargs.items():
        if value is not None:
            setattr(room, key, value)
    await db.flush()
    return room


async def delete_room(db: AsyncSession, room: Room) -> None:
    await db.delete(room)
    await db.flush()


async def get_archived(db: AsyncSession, model: type, record_id: int) -> object | None:
    """Lit une fiche même si elle est dans la corbeille.

    Le filtre global masque les fiches archivées à toutes les lectures : sans
    cette échappée, on ne pourrait ni les restaurer ni les supprimer, autrement
    dit la corbeille serait un cul-de-sac.
    """
    from app.core.archive_filter import INCLUDE_ARCHIVED

    stmt = select(model).where(model.id == record_id)
    result = await db.execute(stmt.execution_options(**{INCLUDE_ARCHIVED: True}))
    return result.scalar_one_or_none()


async def get_archived_student_by_id(db: AsyncSession, student_id: int) -> Student | None:
    """Raccourci typé sur `get_archived` pour les élèves."""
    return await get_archived(db, Student, student_id)  # type: ignore[return-value]
