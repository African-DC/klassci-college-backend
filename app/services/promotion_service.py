"""Service promotions — bulk year rollover (cycle 3 plan B).

Architecture :
- Pre-flight `preview_promotion` valide structure (classes existent, AY différentes,
  mapping non-vide) et retourne summary + warnings capacité.
- Execute `execute_promotion` boucle les élèves source `valide` via
  `enrollment_service.create_enrollment` qui gère naturellement capacity check,
  duplicate guard et auto-création des frais obligatoires.
- Partial-success-with-reporting : si 1 élève fail (capacité dépassée par exemple),
  les autres continuent et l'erreur est listée. Pattern fintech 2024+.
- Idempotency : si l'élève est déjà inscrit dans target_ay, skip silencieux. Permet
  de relancer execute après un crash mid-run sans duplication.
- Audit log : 1 ligne summary par run (entity_type=bulk_promotion).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError
from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.repositories import enrollment_repository as enrollment_repo
from app.schemas.admin import (
    PromotionCapacityWarning,
    PromotionExecuteError,
    PromotionExecuteResponse,
    PromotionPreviewResponse,
    SourceClassSummary,
)

logger = logging.getLogger(__name__)


async def _validate_run_inputs(
    db: AsyncSession,
    *,
    source_ay_id: int,
    target_ay_id: int,
    class_mapping: dict[int, int],
) -> dict[int, Class]:
    """Pre-flight commun preview + execute.

    Retourne le dict `{target_class_id: Class}` pour réutilisation downstream.
    Lève `BusinessValidationError` (422) sur toute violation structurelle.
    """
    if not class_mapping:
        raise BusinessValidationError("Le mapping de classes est vide.")

    if source_ay_id == target_ay_id:
        raise BusinessValidationError("L'année source et l'année cible doivent être différentes.")

    # Refactor #97 : Class est universel, pas de filtre par target_ay_id ici.
    # La capacity/availability AY-cible est calculée downstream via
    # count_active_enrollments_for_class(class_id, target_ay_id).
    target_class_ids = list(set(class_mapping.values()))
    classes_stmt = select(Class).where(Class.id.in_(target_class_ids))
    classes = (await db.execute(classes_stmt)).scalars().all()
    classes_by_id: dict[int, Class] = {c.id: c for c in classes}

    missing = [cid for cid in target_class_ids if cid not in classes_by_id]
    if missing:
        raise BusinessValidationError(
            f"Classes destination introuvables : {missing}. "
            "Créez-les d'abord ou ajustez le mapping."
        )

    return classes_by_id


async def preview_promotion(
    db: AsyncSession,
    *,
    source_ay_id: int,
    target_ay_id: int,
    class_mapping: dict[int, int],
    excluded_enrollment_ids: list[int] | None = None,
) -> PromotionPreviewResponse:
    """Pre-flight + analyse capacités. Ne modifie rien."""
    target_classes = await _validate_run_inputs(
        db,
        source_ay_id=source_ay_id,
        target_ay_id=target_ay_id,
        class_mapping=class_mapping,
    )

    # Compter les élèves valides à promouvoir, groupés par classe source
    source_class_ids = list(class_mapping.keys())
    source_stmt = select(Enrollment.class_id).where(
        Enrollment.academic_year_id == source_ay_id,
        Enrollment.status == EnrollmentStatus.VALIDE,
        Enrollment.class_id.in_(source_class_ids),
    )
    source_rows = (await db.execute(source_stmt)).all()

    counts_by_source: dict[int, int] = {}
    for (class_id,) in source_rows:
        counts_by_source[class_id] = counts_by_source.get(class_id, 0) + 1

    source_summaries: list[SourceClassSummary] = []
    capacity_warnings: list[PromotionCapacityWarning] = []
    promotable_count = 0

    for source_id, target_id in class_mapping.items():
        target = target_classes[target_id]
        nb_to_promote = counts_by_source.get(source_id, 0)
        promotable_count += nb_to_promote

        existing_count = await enrollment_repo.count_active_enrollments_for_class(
            db, target_id, target_ay_id
        )
        remaining = max(0, target.max_students - existing_count)

        source_summaries.append(
            SourceClassSummary(
                source_class_id=source_id,
                target_class_id=target_id,
                target_class_name=target.name,
                students_to_promote=nb_to_promote,
                target_capacity=target.max_students,
                target_remaining=remaining,
            )
        )

        if nb_to_promote > remaining:
            capacity_warnings.append(
                PromotionCapacityWarning(
                    source_class_id=source_id,
                    target_class_id=target_id,
                    target_class_name=target.name,
                    requested=nb_to_promote,
                    available=remaining,
                    overflow=nb_to_promote - remaining,
                )
            )

    return PromotionPreviewResponse(
        source_ay_id=source_ay_id,
        target_ay_id=target_ay_id,
        source_classes=source_summaries,
        capacity_warnings=capacity_warnings,
        promotable_count=promotable_count,
    )


async def execute_promotion(
    db: AsyncSession,
    *,
    source_ay_id: int,
    target_ay_id: int,
    class_mapping: dict[int, int],
    executed_by: int,
    excluded_enrollment_ids: list[int] | None = None,
) -> PromotionExecuteResponse:
    """Execute la promotion bulk. Partial-success + idempotent."""
    await _validate_run_inputs(
        db,
        source_ay_id=source_ay_id,
        target_ay_id=target_ay_id,
        class_mapping=class_mapping,
    )

    source_class_ids = list(class_mapping.keys())
    source_stmt = (
        select(Enrollment)
        .where(
            Enrollment.academic_year_id == source_ay_id,
            Enrollment.status == EnrollmentStatus.VALIDE,
            Enrollment.class_id.in_(source_class_ids),
        )
        .order_by(Enrollment.id)
    )
    source_enrollments = list((await db.execute(source_stmt)).scalars().all())

    # Redoublants, departs, exclusions : ecartes AVANT la boucle. Promouvoir
    # tout le monde puis annuler a la main est irrealiste sur trois cents
    # eleves, et le redoublement n'est pas un cas marginal ici.
    excluded = set(excluded_enrollment_ids or ())
    if excluded:
        source_enrollments = [e for e in source_enrollments if e.id not in excluded]

    promoted_ids: list[int] = []
    skipped_count = 0
    errors: list[PromotionExecuteError] = []

    # Import dynamique pour éviter circular import enrollment_service ↔ promotion_service
    from app.schemas.enrollment import EnrollmentCreate
    from app.services import enrollment_service

    for source_enrollment in source_enrollments:
        target_class_id = class_mapping.get(source_enrollment.class_id)
        if target_class_id is None:
            errors.append(
                PromotionExecuteError(
                    student_id=source_enrollment.student_id,
                    source_enrollment_id=source_enrollment.id,
                    reason="Classe source non mappée.",
                )
            )
            continue

        # Idempotency : si déjà inscrit dans target_ay, skip silencieux
        existing = await enrollment_repo.get_active_enrollment(
            db, source_enrollment.student_id, target_ay_id
        )
        if existing is not None:
            skipped_count += 1
            continue

        try:
            new_data = EnrollmentCreate(
                student_id=source_enrollment.student_id,
                class_id=target_class_id,
                academic_year_id=target_ay_id,
                fee_variant_id=None,
                notes=None,
            )
            new_enrollment = await enrollment_service.create_enrollment(
                db, new_data, created_by=executed_by
            )
            promoted_ids.append(new_enrollment.id)
        except BusinessValidationError as exc:
            errors.append(
                PromotionExecuteError(
                    student_id=source_enrollment.student_id,
                    source_enrollment_id=source_enrollment.id,
                    reason=exc.detail,
                )
            )
        except Exception:
            logger.exception("Unexpected error promoting enrollment %s", source_enrollment.id)
            errors.append(
                PromotionExecuteError(
                    student_id=source_enrollment.student_id,
                    source_enrollment_id=source_enrollment.id,
                    reason="Erreur inattendue, voir les logs.",
                )
            )

    # Audit log summary — 1 ligne par run, garde la trace sans saturer la table
    await audit_log(
        db,
        entity_type="bulk_promotion",
        action=AuditAction.UPDATE,
        user_id=executed_by,
        entity_id=target_ay_id,
        new_values={
            "source_ay_id": source_ay_id,
            "target_ay_id": target_ay_id,
            "class_mapping": {str(k): v for k, v in class_mapping.items()},
            "excluded_enrollment_ids": sorted(excluded),
            "promoted_count": len(promoted_ids),
            "skipped_count": skipped_count,
            "error_count": len(errors),
        },
    )
    await db.commit()

    return PromotionExecuteResponse(
        source_ay_id=source_ay_id,
        target_ay_id=target_ay_id,
        promoted_count=len(promoted_ids),
        promoted_enrollment_ids=promoted_ids,
        skipped_count=skipped_count,
        error_count=len(errors),
        errors=errors,
    )
