"""Router inscriptions — CRUD /enrollments + documents.

Les endpoints paiements `/enrollments/{id}/payments` sont dans
`enrollment_payments.py` (séparation par sous-domaine, anti-god-code).
"""

from fastapi import APIRouter, Depends, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.enrollment import (
    DocumentResponse,
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithStudentCreate,
    FeeVariantResponse,
    ReEnrollmentCreate,
    SubscribeOptionRequest,
)
from app.services import enrollment_service

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("", response_model=EnrollmentListResponse)
async def list_enrollments(
    class_id: int | None = Query(None),
    student_id: int | None = Query(None),
    status: str | None = Query(None),
    academic_year_id: int | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentListResponse:
    """Liste paginée des inscriptions avec filtres optionnels."""
    return await enrollment_service.list_enrollments(
        db,
        class_id=class_id,
        student_id=student_id,
        status=status,
        academic_year_id=academic_year_id,
        search=search,
        page=page,
        size=size,
    )


@router.post("", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    data: EnrollmentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Crée une nouvelle inscription."""
    return await enrollment_service.create_enrollment(db, data, created_by=current_user.user_id)


@router.post(
    "/with-student",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_enrollment_with_student(
    data: EnrollmentWithStudentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Cree un eleve + parent optionnel + inscription en une seule operation."""
    return await enrollment_service.create_enrollment_with_student(
        db, data, created_by=current_user.user_id
    )


@router.post(
    "/re-enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def re_enroll_student(
    data: ReEnrollmentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Re-inscrit un eleve existant dans une nouvelle classe/annee."""
    return await enrollment_service.re_enroll_student(db, data, created_by=current_user.user_id)


@router.get("/fee-variants", response_model=list[FeeVariantResponse])
async def get_applicable_fee_variants(
    class_id: int = Query(..., description="ID de la classe pour la resolution des frais"),
    academic_year_id: int | None = Query(
        None,
        description=(
            "AY pour le matching des frais. Si omis, l'AY courante est utilisée. "
            "Class étant universel (refactor #97), l'AY n'est plus inférée depuis la classe."
        ),
    ),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeVariantResponse]:
    """Retourne les fee variants applicables pour une classe donnee."""
    return await enrollment_service.get_applicable_fee_variants(db, class_id, academic_year_id)


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Retourne une inscription par ID."""
    return await enrollment_service.get_enrollment(db, enrollment_id)


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    data: EnrollmentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Met à jour le statut ou les notes d'une inscription (patch partiel)."""
    return await enrollment_service.update_enrollment(
        db, enrollment_id, data, updated_by=current_user.user_id
    )


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_enrollment(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une inscription."""
    await enrollment_service.delete_enrollment(db, enrollment_id, deleted_by=current_user.user_id)


@router.post(
    "/{enrollment_id}/validate",
    response_model=EnrollmentResponse,
    summary="Valider une inscription",
    description=(
        "Transitionne une inscription `prospect` ou `en_validation` vers `valide`. "
        "Endpoint dédié pour audit log explicite et transition guard. Refuse les "
        "autres statuts avec 422."
    ),
)
async def validate_enrollment(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Valide une inscription (transition prospect/en_validation → valide)."""
    return await enrollment_service.validate_enrollment(
        db, enrollment_id, validated_by=current_user.user_id
    )


# ---------------------------------------------------------------------------
# Optional fee subscriptions
# ---------------------------------------------------------------------------


@router.post(
    "/{enrollment_id}/options",
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_option(
    enrollment_id: int,
    data: SubscribeOptionRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Souscrit un élève à une option de frais facultatif."""
    async with db.begin_nested():
        result = await enrollment_service.subscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            optional_fee_option_id=data.optional_fee_option_id,
            created_by=current_user.user_id,
        )
    await db.commit()
    return result


@router.delete(
    "/{enrollment_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsubscribe_option(
    enrollment_id: int,
    option_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Désinscrit un élève d'une option de frais facultatif."""
    async with db.begin_nested():
        await enrollment_service.unsubscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            option_id=option_id,
            deleted_by=current_user.user_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@router.post(
    "/{enrollment_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    enrollment_id: int,
    file: UploadFile,
    doc_type: str = Query("autre", description="Type de document: bulletin, acte_naissance, etc."),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> DocumentResponse:
    """Upload un document justificatif pour une inscription."""
    return await enrollment_service.upload_document(
        db,
        enrollment_id=enrollment_id,
        file=file,
        doc_type=doc_type,
        uploaded_by=current_user.user_id,
    )


@router.get("/{enrollment_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[DocumentResponse]:
    """Liste les documents d'une inscription."""
    return await enrollment_service.list_documents(db, enrollment_id)
