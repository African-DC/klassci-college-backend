"""Billet d'annulation de zéro : rouvrir des évaluations réellement manquées.

Le billet change le statut des notes visées, il n'en saisit jamais la valeur.
La note de rattrapage reste la main de l'enseignant : un acte administratif qui
modifierait une moyenne tout seul est exactement ce qu'un conseil de classe
finit par contester.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.grade import Evaluation, Grade, GradeStatus
from app.models.school_life import RetakeAuthorization, RetakeAuthorizationEvaluation
from app.schemas.school_life import (
    RetakeAuthorizationCreate,
    RetakeAuthorizationList,
    RetakeAuthorizationResponse,
    RetakeTargetResponse,
)
from app.services.school_life._common import (
    StudentContext,
    actor_name,
    current_class_names,
    issue_act_seal,
    load_student_context,
)

DOCUMENT_TYPE = "annulation_zero"


async def _get_authorization(db: AsyncSession, authorization_id: int) -> RetakeAuthorization:
    """Charge une autorisation et sa chaîne complète — lue après `commit()`."""
    stmt = (
        select(RetakeAuthorization)
        .where(RetakeAuthorization.id == authorization_id)
        .options(
            selectinload(RetakeAuthorization.student),
            selectinload(RetakeAuthorization.academic_year),
            selectinload(RetakeAuthorization.targets)
            .selectinload(RetakeAuthorizationEvaluation.evaluation)
            .selectinload(Evaluation.subject),
        )
    )
    authorization = (await db.execute(stmt)).scalar_one_or_none()
    if authorization is None:
        raise NotFoundError("RetakeAuthorization", authorization_id)
    return authorization


async def _load_missed_grades(
    db: AsyncSession, *, student_id: int, evaluation_ids: list[int]
) -> list[Grade]:
    """Notes de l'élève sur les évaluations visées, avec leur évaluation.

    On charge tout d'un coup pour pouvoir refuser d'un seul message : dire à
    l'éducateur « la deuxième ligne ne va pas » après avoir accepté la
    première serait une demi-validation.
    """
    stmt = (
        select(Grade)
        .where(Grade.student_id == student_id, Grade.evaluation_id.in_(evaluation_ids))
        .options(selectinload(Grade.evaluation).selectinload(Evaluation.subject))
    )
    return list((await db.execute(stmt)).scalars().all())


def _validate_targets(
    grades: list[Grade],
    *,
    evaluation_ids: list[int],
    context: StudentContext,
) -> int:
    """Vérifie que chaque évaluation visée a bien été manquée, et renvoie le trimestre."""
    by_evaluation = {grade.evaluation_id: grade for grade in grades}

    unknown = [eid for eid in evaluation_ids if eid not in by_evaluation]
    if unknown:
        raise BusinessValidationError(
            "Cet élève n'est pas rattaché aux évaluations suivantes : "
            f"{', '.join(str(eid) for eid in unknown)}."
        )

    not_missed: list[str] = []
    trimesters: set[int] = set()
    for eid in evaluation_ids:
        grade = by_evaluation[eid]
        status = grade.status.value if hasattr(grade.status, "value") else grade.status
        if status != GradeStatus.ABSENT.value:
            not_missed.append(grade.evaluation.title if grade.evaluation else str(eid))
        if grade.evaluation is not None:
            trimesters.add(grade.evaluation.trimester)

    if not_missed:
        raise BusinessValidationError(
            "Un rattrapage ne s'autorise que sur une évaluation réellement manquée. "
            "Ces évaluations ne sont pas marquées « absent » pour cet élève : "
            f"{', '.join(not_missed)}."
        )
    if len(trimesters) > 1:
        raise BusinessValidationError(
            "Un billet ne couvre qu'un seul trimestre. Établissez-en un par trimestre concerné."
        )
    if not trimesters:
        raise BusinessValidationError("Les évaluations visées n'ont pas de trimestre renseigné.")

    _ = context  # le contexte cadre l'appel ; la validation ne lit que les notes
    return trimesters.pop()


def _to_response(
    authorization: RetakeAuthorization,
    *,
    class_name: str | None,
    issued_by_name: str | None,
) -> RetakeAuthorizationResponse:
    student = authorization.student
    targets = [
        RetakeTargetResponse(
            evaluation_id=target.evaluation_id,
            title=target.evaluation.title,
            subject_name=target.evaluation.subject.name if target.evaluation.subject else None,
            date=target.evaluation.date,
            coefficient=target.evaluation.coefficient,
            trimester=target.evaluation.trimester,
        )
        for target in authorization.targets
        if target.evaluation is not None
    ]
    return RetakeAuthorizationResponse(
        id=authorization.id,
        student_id=authorization.student_id,
        student_name=f"{student.first_name} {student.last_name}".strip(),
        enrollment_number=student.enrollment_number,
        class_name=class_name,
        academic_year_id=authorization.academic_year_id,
        academic_year_name=authorization.academic_year.name
        if authorization.academic_year
        else None,
        trimester=authorization.trimester,
        period_start=authorization.period_start,
        period_end=authorization.period_end,
        reason=authorization.reason,
        reference=authorization.reference,
        issued_by_user_id=authorization.issued_by_user_id,
        issued_by_name=issued_by_name,
        evaluations=targets,
        created_at=authorization.created_at,
    )


async def create_authorization(
    db: AsyncSession, data: RetakeAuthorizationCreate, *, actor_id: int
) -> RetakeAuthorizationResponse:
    """Rouvre les évaluations manquées d'un élève pour une période donnée."""
    context = await load_student_context(db, data.student_id)
    grades = await _load_missed_grades(
        db, student_id=data.student_id, evaluation_ids=data.evaluation_ids
    )
    trimester = _validate_targets(grades, evaluation_ids=data.evaluation_ids, context=context)

    authorization = RetakeAuthorization(
        student_id=data.student_id,
        academic_year_id=context.academic_year_id,
        trimester=trimester,
        period_start=data.period_start,
        period_end=data.period_end,
        reason=data.reason,
        issued_by_user_id=actor_id,
    )
    db.add(authorization)
    await db.flush()

    for evaluation_id in data.evaluation_ids:
        db.add(
            RetakeAuthorizationEvaluation(
                authorization_id=authorization.id, evaluation_id=evaluation_id
            )
        )

    for grade in grades:
        # Le zéro d'office est levé, la case redevient à remplir — mais par
        # l'enseignant, et sur sa feuille de notes habituelle.
        grade.status = GradeStatus.RETAKE_ALLOWED
        grade.value = None
        await audit_log(
            db,
            entity_type="grade",
            entity_id=grade.id,
            action=AuditAction.UPDATE,
            user_id=actor_id,
            old_values={"status": GradeStatus.ABSENT.value},
            new_values={"status": GradeStatus.RETAKE_ALLOWED.value},
            notes=f"Billet d'annulation de zéro #{authorization.id}",
        )

    await audit_log(
        db,
        entity_type="retake_authorization",
        entity_id=authorization.id,
        action=AuditAction.CREATE,
        user_id=actor_id,
        new_values={
            "student_id": data.student_id,
            "trimester": trimester,
            "evaluation_ids": data.evaluation_ids,
        },
    )
    await db.commit()

    refreshed = await _get_authorization(db, authorization.id)
    return _to_response(
        refreshed,
        class_name=context.class_name,
        issued_by_name=await actor_name(db, actor_id),
    )


async def list_missed_evaluations(
    db: AsyncSession, *, student_id: int, period_start: date, period_end: date
) -> list[RetakeTargetResponse]:
    """Épreuves qu'un élève a manquées sur une fenêtre d'absence.

    C'est exactement le lot que `create_authorization` accepte de rouvrir : le
    guichet ne doit proposer que ce que la règle métier acceptera ensuite.

    Le croisement se fait ici, en une requête, parce qu'il appartient au
    bureau de la vie scolaire. Le reconstituer côté écran obligeait à lire le
    cahier de notes de la classe — un droit que ni l'éducateur ni le
    secrétariat n'ont, et qu'ils n'ont pas à avoir pour lever un zéro.
    """
    if period_end < period_start:
        raise BusinessValidationError("La fin de la période doit suivre son début.")

    stmt = (
        select(Grade)
        .join(Grade.evaluation)
        .where(
            Grade.student_id == student_id,
            Grade.status == GradeStatus.ABSENT.value,
            Evaluation.date >= period_start,
            Evaluation.date <= period_end,
        )
        .options(selectinload(Grade.evaluation).selectinload(Evaluation.subject))
        .order_by(Evaluation.date, Evaluation.id)
    )
    grades = (await db.execute(stmt)).scalars().all()
    return [
        RetakeTargetResponse(
            evaluation_id=grade.evaluation.id,
            title=grade.evaluation.title,
            subject_name=grade.evaluation.subject.name if grade.evaluation.subject else None,
            date=grade.evaluation.date,
            coefficient=grade.evaluation.coefficient,
            trimester=grade.evaluation.trimester,
        )
        for grade in grades
        if grade.evaluation is not None
    ]


async def list_authorizations(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
    trimester: int | None = None,
    student_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> RetakeAuthorizationList:
    """Autorisations délivrées, de la plus récente à la plus ancienne.

    Paginé : un registre s'empile d'une année sur l'autre et n'est jamais
    purgé, alors que la question posée devant l'écran porte toujours sur les
    dernières lignes.
    """
    filters = []
    if academic_year_id is not None:
        filters.append(RetakeAuthorization.academic_year_id == academic_year_id)
    if trimester is not None:
        filters.append(RetakeAuthorization.trimester == trimester)
    if student_id is not None:
        filters.append(RetakeAuthorization.student_id == student_id)

    total = int(
        (
            await db.execute(select(func.count()).select_from(RetakeAuthorization).where(*filters))
        ).scalar_one()
    )
    # Le nombre d'épreuves rouvertes est la mesure que le bureau regarde en
    # premier, et elle ne se déduit pas d'une page : la compter sur les lignes
    # affichées reviendrait à la faire varier avec la pagination.
    reopened = int(
        (
            await db.execute(
                select(func.count())
                .select_from(RetakeAuthorizationEvaluation)
                .join(RetakeAuthorizationEvaluation.authorization)
                .where(*filters)
            )
        ).scalar_one()
    )

    stmt = (
        select(RetakeAuthorization)
        .where(*filters)
        .options(
            selectinload(RetakeAuthorization.student),
            selectinload(RetakeAuthorization.academic_year),
            selectinload(RetakeAuthorization.targets)
            .selectinload(RetakeAuthorizationEvaluation.evaluation)
            .selectinload(Evaluation.subject),
        )
        .order_by(RetakeAuthorization.period_start.desc(), RetakeAuthorization.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )

    rows = list((await db.execute(stmt)).scalars().all())
    issuers = {uid: await actor_name(db, uid) for uid in {r.issued_by_user_id for r in rows}}
    class_names = await current_class_names(db, {row.student_id for row in rows})
    return RetakeAuthorizationList(
        items=[
            _to_response(
                row,
                class_name=class_names.get(row.student_id),
                issued_by_name=issuers.get(row.issued_by_user_id),
            )
            for row in rows
        ],
        total=total,
        reopened_evaluations=reopened,
        page=page,
        size=size,
    )


async def compose_document_data(db: AsyncSession, authorization_id: int) -> dict[str, Any]:
    """Scelle le billet et renvoie de quoi l'imprimer."""
    authorization = await _get_authorization(db, authorization_id)
    context = await load_student_context(db, authorization.student_id)
    issued_at = datetime.utcnow()

    evaluations = [
        {
            "subject_name": target.evaluation.subject.name if target.evaluation.subject else None,
            "title": target.evaluation.title,
            "date": target.evaluation.date,
            "coefficient": target.evaluation.coefficient,
        }
        for target in authorization.targets
        if target.evaluation is not None
    ]

    source_data: dict[str, Any] = {
        "student": context.student_payload(),
        "class_name": context.class_name,
        "academic_year_name": context.academic_year_name,
        "period_start": authorization.period_start,
        "period_end": authorization.period_end,
        "reason": authorization.reason,
        "evaluations": evaluations,
        "school_settings": context.school_settings,
    }
    verification = await issue_act_seal(
        db,
        document_type=DOCUMENT_TYPE,
        ref_prefix="BAZ",
        context=context,
        issued_at=issued_at,
        source_data=source_data,
        # Un élève peut avoir un billet par trimestre : sans cet identifiant,
        # celui du T2 périmerait celui du T1, déjà remis à l'enseignant.
        act_id=authorization.id,
    )
    authorization.reference = verification["reference"]
    await db.commit()

    return {
        **source_data,
        "issued_at": issued_at,
        "reference": verification["reference"],
        "verification": verification,
        "school_settings": context.school_settings,
        "student_last_name": context.student.last_name,
    }
