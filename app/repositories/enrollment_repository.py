"""Repository inscriptions — accès DB pour Enrollment et EnrollmentFee."""

from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear, Class
from app.models.enrollment import AssignmentStatus, Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, FeeVariant
from app.models.user import Student

#: « Champ absent », a distinguer d'un `None` envoye exprès. Sur
#: `is_new_student`, `None` est une valeur metier — « on n'a pas tranche » —
#: et non une absence : sans cette sentinelle, une decision posee par erreur
#: ne se retirerait plus jamais depuis l'ecran.
UNSET: object = object()


async def get_enrollment_by_id(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Retourne une inscription par ID avec ses relations chargées."""
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_),
            selectinload(Enrollment.enrollment_fees).selectinload(EnrollmentFee.fee_variant),
            selectinload(Enrollment.scholarship),
            # Pas de `EnrollmentFee.payments` ici : la relation est dépréciée
            # depuis la migration 0028 et plus personne ne la lit. La charger
            # coûtait une requête par appel pour un résultat toujours vide.
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


#: Pastilles « Affectation » de la liste. Affecté et réaffecté forment une
#: seule cohorte : l'État subventionne les deux.
ASSIGNMENT_FILTERS = ("affectes", "non_affectes", "non_renseigne")


def _assignment_clause(assignment: str) -> ColumnElement[bool]:
    if assignment == "affectes":
        return Enrollment.assignment_status.in_(
            (AssignmentStatus.AFFECTE.value, AssignmentStatus.REAFFECTE.value)
        )
    if assignment == "non_affectes":
        return Enrollment.assignment_status == AssignmentStatus.NON_AFFECTE.value
    return Enrollment.assignment_status.is_(None)


def _filtered(
    base: Select[Any],
    *,
    class_id: int | None = None,
    student_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    search: str | None = None,
) -> Select[Any]:
    """Les filtres de la liste, partagés avec le décompte des pastilles.

    Une seule définition : sinon une pastille annoncerait un nombre que la
    liste, filtrée autrement, ne montrerait pas.
    """
    if class_id is not None:
        base = base.where(Enrollment.class_id == class_id)
    if student_id is not None:
        base = base.where(Enrollment.student_id == student_id)
    if status == "a_valider":
        base = base.where(
            Enrollment.status.in_(
                (EnrollmentStatus.PROSPECT.value, EnrollmentStatus.EN_VALIDATION.value)
            )
        )
    elif status is not None:
        base = base.where(Enrollment.status == status)
    if academic_year_id is not None:
        base = base.where(Enrollment.academic_year_id == academic_year_id)
    if search:
        words = search.strip().split()
        base = base.join(Student, Enrollment.student_id == Student.id)
        for word in words:
            pattern = f"%{word}%"
            base = base.where(
                or_(Student.first_name.ilike(pattern), Student.last_name.ilike(pattern))
            )
    return base


async def list_enrollments(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    student_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    search: str | None = None,
    assignment: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Enrollment], int]:
    """Retourne une page d'inscriptions avec le total."""
    base = _filtered(
        select(Enrollment).options(
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_),
            selectinload(Enrollment.enrollment_fees).selectinload(EnrollmentFee.fee_variant),
            selectinload(Enrollment.scholarship),
        ),
        class_id=class_id,
        student_id=student_id,
        status=status,
        academic_year_id=academic_year_id,
        search=search,
    )
    if assignment is not None:
        base = base.where(_assignment_clause(assignment))

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Enrollment.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def assignment_counts(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    search: str | None = None,
) -> dict[str, int]:
    """Total par pastille « Affectation », sur tous les résultats filtrés.

    La liste se charge par pages : compter les lignes affichées donnait des
    pastilles fausses dès qu'il restait des inscriptions à charger.
    """
    stmt = _filtered(
        select(Enrollment.assignment_status, func.count(Enrollment.id)),
        class_id=class_id,
        status=status,
        academic_year_id=academic_year_id,
        search=search,
    ).group_by(Enrollment.assignment_status)
    par_statut = {statut: int(n) for statut, n in (await db.execute(stmt)).all()}
    affectes = par_statut.get(AssignmentStatus.AFFECTE.value, 0) + par_statut.get(
        AssignmentStatus.REAFFECTE.value, 0
    )
    return {
        "tous": sum(par_statut.values()),
        "affectes": affectes,
        "non_affectes": par_statut.get(AssignmentStatus.NON_AFFECTE.value, 0),
        "non_renseigne": par_statut.get(None, 0),
    }


async def create_enrollment(
    db: AsyncSession,
    *,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    created_by: int | None,
    notes: str | None,
    assignment_status: str | None = None,
    assignment_decision_number: str | None = None,
    is_new_student: bool | None = None,
) -> Enrollment:
    """Crée une inscription et la flush pour obtenir l'ID."""
    enrollment = Enrollment(
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        created_by=created_by,
        notes=notes,
        assignment_status=assignment_status,
        assignment_decision_number=assignment_decision_number,
        is_new_student=is_new_student,
    )
    db.add(enrollment)
    await db.flush()
    return enrollment


async def create_enrollment_fee(
    db: AsyncSession,
    *,
    enrollment_id: int,
    fee_variant_id: int,
) -> EnrollmentFee:
    """Crée un EnrollmentFee en récupérant le montant depuis FeeVariant.

    Ne teste AUCUNE dimension du tarif : ni la série, ni le statut
    d'affectation, ni le profil d'élève. Un appelant qui reçoit un
    `fee_variant_id` d'un client passe donc par
    `enrollment_fees.create_explicit_enrollment_fee`, qui pose le garde avant
    d'appeler d'ici. Écrire directement ici depuis un corps de requête
    contournerait l'invariant que tout le reste du code tient.
    """
    variant_stmt = select(FeeVariant).where(FeeVariant.id == fee_variant_id)
    variant = (await db.execute(variant_stmt)).scalar_one_or_none()
    if variant is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("FeeVariant", fee_variant_id)

    fee = EnrollmentFee(
        enrollment_id=enrollment_id,
        fee_variant_id=fee_variant_id,
        # Recopiee du tarif : c'est elle que porte la contrainte
        # `uq_enrollment_fee_category`, une categorie par inscription.
        fee_category_id=variant.fee_category_id,
        amount=variant.amount,
    )
    db.add(fee)
    await db.flush()
    return fee


async def update_enrollment(
    db: AsyncSession,
    enrollment: Enrollment,
    *,
    status: str | None = None,
    notes: str | None = None,
    class_id: int | None = None,
    is_new_student: object = UNSET,
    assignment_status: object = UNSET,
    assignment_decision_number: object = UNSET,
) -> Enrollment:
    """Met à jour les champs modifiables d'une inscription."""
    if status is not None:
        enrollment.status = status
    if notes is not None:
        enrollment.notes = notes
    if class_id is not None:
        enrollment.class_id = class_id
    # Le seul champ dont `None` est une valeur, pas une absence : c'est ce qui
    # permet de remettre une inscription à « on n'a pas tranché ».
    if is_new_student is not UNSET:
        enrollment.is_new_student = is_new_student
    # Même sentinelle : `None` veut dire « non renseigné », pas « laisser tel
    # quel ». Sans ça, corriger l'affectation depuis la fiche n'écrivait rien.
    if assignment_status is not UNSET:
        enrollment.assignment_status = assignment_status
    if assignment_decision_number is not UNSET:
        enrollment.assignment_decision_number = assignment_decision_number
    await db.flush()
    return enrollment


async def delete_enrollment(db: AsyncSession, enrollment: Enrollment) -> None:
    """Supprime une inscription."""
    await db.delete(enrollment)
    await db.flush()


async def get_active_enrollment(
    db: AsyncSession, student_id: int, academic_year_id: int
) -> Enrollment | None:
    """Retourne une inscription active existante (pour détecter les doublons)."""
    stmt = select(Enrollment).where(
        Enrollment.student_id == student_id,
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status != EnrollmentStatus.ANNULE,
        Enrollment.status != EnrollmentStatus.REJETE,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_class_by_id(db: AsyncSession, class_id: int) -> Class | None:
    """Retourne une classe par ID."""
    return (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()


async def get_class_by_id_for_update(db: AsyncSession, class_id: int) -> Class | None:
    """Retourne une classe avec verrou FOR UPDATE (capacity guard dans transaction)."""
    stmt = select(Class).where(Class.id == class_id).with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def count_active_enrollments_for_class(
    db: AsyncSession,
    class_id: int,
    academic_year_id: int,
) -> int:
    """Compte les inscriptions non-terminées dans une classe pour une AY donnée.

    Refactor #97 : Class est universel, donc le compte par-classe doit être
    scopé à l'AY pour ne pas additionner les cohortes des années précédentes.
    """
    stmt = (
        select(func.count())
        .select_from(Enrollment)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
    )
    return (await db.execute(stmt)).scalar() or 0


async def get_academic_year_by_id(db: AsyncSession, academic_year_id: int) -> AcademicYear | None:
    """Retourne une année scolaire par ID."""
    stmt = select(AcademicYear).where(AcademicYear.id == academic_year_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
