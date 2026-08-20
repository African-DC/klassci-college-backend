"""Router promotions — bulk year rollover (cycle 3 plan B).

Deux endpoints :
- `POST /admin/promotions/preview` : pre-flight, retourne summary + warnings capacité.
  Aucune mutation. À appeler depuis le wizard FE pour afficher le résumé.
- `POST /admin/promotions/execute` : exécute la promotion bulk avec partial-success
  reporting + idempotency (skip si déjà inscrit dans target_ay).

Permission : `enrollments:promote` (à seeder dans `tenant_service.ALL_PERMISSIONS`).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    require_permission,
)
from app.schemas.admin import (
    PromotionExecuteRequest,
    PromotionExecuteResponse,
    PromotionPreviewRequest,
    PromotionPreviewResponse,
)
from app.services import promotion_service

router = APIRouter(prefix="/admin/promotions", tags=["promotions"])


@router.post("/preview", response_model=PromotionPreviewResponse)
async def preview_promotion(
    data: PromotionPreviewRequest,
    _: None = require_permission("enrollments:promote"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PromotionPreviewResponse:
    """Pre-flight d'une promotion bulk : valide la structure et retourne le
    résumé + warnings capacité. Ne modifie rien.

    Erreurs structurelles (classes destination introuvables, AY identiques,
    mapping vide) → 422 BusinessValidationError.

    Les warnings capacité (overflow attendu) ne bloquent pas — l'admin peut
    décider d'exécuter quand même (les élèves en surnombre remonteront en
    `errors` à l'execute).
    """
    return await promotion_service.preview_promotion(
        db,
        source_ay_id=data.source_ay_id,
        target_ay_id=data.target_ay_id,
        class_mapping=data.class_mapping,
        excluded_enrollment_ids=data.excluded_enrollment_ids,
    )


@router.post("/execute", response_model=PromotionExecuteResponse)
async def execute_promotion(
    data: PromotionExecuteRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:promote"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PromotionExecuteResponse:
    """Exécute la promotion bulk avec partial-success reporting.

    Idempotent : retry safe via `get_active_enrollment` per-student qui skip
    les élèves déjà inscrits dans `target_ay_id`.

    Audit log : 1 ligne summary `entity_type=bulk_promotion` par run, contient
    le mapping + counts + errors. Pas de saturation de la table audit.
    """
    return await promotion_service.execute_promotion(
        db,
        source_ay_id=data.source_ay_id,
        target_ay_id=data.target_ay_id,
        class_mapping=data.class_mapping,
        executed_by=current_user.user_id,
        excluded_enrollment_ids=data.excluded_enrollment_ids,
    )
