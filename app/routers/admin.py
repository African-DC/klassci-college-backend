"""Router admin — CRUD endpoints pour les entités de base."""

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.admin import (
    AcademicYearCreate,
    AcademicYearListResponse,
    AcademicYearResponse,
    AcademicYearUpdate,
    ClassCreate,
    ClassListResponse,
    ClassResponse,
    ClassUpdate,
    EnrollmentPatternPreview,
    EnrollmentPatternUpdate,
    LevelCreate,
    LevelListResponse,
    LevelResponse,
    LevelUpdate,
    ParentCreate,
    ParentFullResponse,
    ParentLinkBody,
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
    SchoolSettingsResponse,
    SeriesCreate,
    SeriesListResponse,
    SeriesResponse,
    SeriesUpdate,
    StaffCreate,
    StaffFullResponse,
    StaffListResponse,
    StaffResponse,
    StaffUpdate,
    StudentCreate,
    StudentEnrollmentFeeListResponse,
    StudentFullResponse,
    StudentListResponse,
    StudentResponse,
    StudentUpdate,
    SubjectCreate,
    SubjectDuplicateRequest,
    SubjectListResponse,
    SubjectResponse,
    SubjectUpdate,
    TeacherCreate,
    TeacherFullResponse,
    TeacherListResponse,
    TeacherResponse,
    TeacherUpdate,
    UserAccountCreate,
    UserAccountUpdate,
)
from app.services import admin_service, enrollment_service, matricule_service

router = APIRouter(prefix="/admin", tags=["admin"])

UPLOAD_DIR = "/tmp/klassci-uploads/photos"


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


@router.get("/students", response_model=StudentListResponse)
async def list_students(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentListResponse:
    """Liste paginee des eleves avec recherche optionnelle."""
    return await admin_service.list_students(db, page=page, size=size, search=search)


@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    data: StudentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentResponse:
    """Cree un nouvel eleve."""
    return await admin_service.create_student(db, data, created_by=current_user.user_id)


@router.get("/students/{student_id}/full", response_model=StudentFullResponse)
async def get_student_full(
    student_id: int,
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Retourne le profil complet d'un eleve avec KPIs."""
    return await admin_service.get_student_full(db, student_id)


@router.get("/students/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: int,
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentResponse:
    """Retourne un eleve par ID."""
    return await admin_service.get_student(db, student_id)


@router.patch("/students/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: int,
    data: StudentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentResponse:
    """Met a jour un eleve (patch partiel)."""
    return await admin_service.update_student(db, student_id, data, updated_by=current_user.user_id)


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un eleve."""
    await admin_service.delete_student(db, student_id, deleted_by=current_user.user_id)


@router.post("/students/{student_id}/photo")
async def upload_student_photo(
    student_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Upload ou remplace la photo de profil d'un eleve."""
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Format invalide. Accepte: JPEG, PNG, WebP")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"{student_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 5 Mo)")

    with open(filepath, "wb") as f:
        f.write(content)

    photo_url = f"/uploads/photos/{filename}"
    student = await admin_service.update_student_photo(
        db, student_id, photo_url, updated_by=current_user.user_id
    )
    return {"photo_url": student.photo_url}


@router.delete("/students/{student_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_photo(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime la photo de profil d'un eleve."""
    await admin_service.update_student_photo(db, student_id, None, updated_by=current_user.user_id)


@router.post("/students/{student_id}/account")
async def create_student_account(
    student_id: int,
    data: UserAccountCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Cree un compte utilisateur pour un eleve existant sans compte."""
    result = await admin_service.create_student_user_account(
        db, student_id, data.email, data.password, created_by=current_user.user_id
    )
    return result


@router.get(
    "/students/{student_id}/fees",
    response_model=StudentEnrollmentFeeListResponse,
)
async def get_student_fees(
    student_id: int,
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentEnrollmentFeeListResponse:
    """Retourne les frais d'inscription d'un élève avec détails de paiement."""
    return await admin_service.get_student_enrollment_fees(db, student_id)


# ---------------------------------------------------------------------------
# Enrollment fees — regenerate
# ---------------------------------------------------------------------------


@router.post("/enrollments/{enrollment_id}/regenerate-fees")
async def regenerate_enrollment_fees(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Régénère les frais obligatoires d'une inscription.

    Supprime les frais sans paiements et recrée les frais obligatoires
    correspondant à la classe actuelle.
    """
    async with db.begin_nested():
        result = await enrollment_service.regenerate_enrollment_fees(
            db, enrollment_id, regenerated_by=current_user.user_id
        )
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# User account management
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}")
async def update_user_account(
    user_id: int,
    data: UserAccountUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Met à jour l'email et/ou le mot de passe d'un compte utilisateur."""
    return await admin_service.update_user_account(
        db, user_id, email=data.email, password=data.password, updated_by=current_user.user_id
    )


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------


@router.get("/teachers", response_model=TeacherListResponse)
async def list_teachers(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherListResponse:
    """Liste paginee des enseignants."""
    return await admin_service.list_teachers(db, page=page, size=size, search=search)


@router.post("/teachers", response_model=TeacherResponse, status_code=status.HTTP_201_CREATED)
async def create_teacher(
    data: TeacherCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherResponse:
    """Cree un nouvel enseignant."""
    return await admin_service.create_teacher(db, data, created_by=current_user.user_id)


@router.get("/teachers/{teacher_id}/full", response_model=TeacherFullResponse)
async def get_teacher_full(
    teacher_id: int,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Retourne le profil complet d'un enseignant avec KPIs."""
    return await admin_service.get_teacher_full(db, teacher_id)


@router.get("/teachers/{teacher_id}", response_model=TeacherResponse)
async def get_teacher(
    teacher_id: int,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherResponse:
    """Retourne un enseignant par ID."""
    return await admin_service.get_teacher(db, teacher_id)


@router.patch("/teachers/{teacher_id}", response_model=TeacherResponse)
async def update_teacher(
    teacher_id: int,
    data: TeacherUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherResponse:
    """Met a jour un enseignant (patch partiel)."""
    return await admin_service.update_teacher(db, teacher_id, data, updated_by=current_user.user_id)


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher(
    teacher_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un enseignant."""
    await admin_service.delete_teacher(db, teacher_id, deleted_by=current_user.user_id)


@router.post("/teachers/{teacher_id}/photo")
async def upload_teacher_photo(
    teacher_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Upload ou remplace la photo de profil d'un enseignant."""
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Format invalide. Accepte: JPEG, PNG, WebP")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"teacher_{teacher_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 5 Mo)")

    with open(filepath, "wb") as f:
        f.write(content)

    photo_url = f"/uploads/photos/{filename}"
    teacher = await admin_service.update_teacher_photo(
        db, teacher_id, photo_url, updated_by=current_user.user_id
    )
    return {"photo_url": teacher.photo_url}


@router.delete("/teachers/{teacher_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher_photo(
    teacher_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime la photo de profil d'un enseignant."""
    await admin_service.update_teacher_photo(db, teacher_id, None, updated_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


@router.get("/staff", response_model=StaffListResponse)
async def list_staff(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:staff:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StaffListResponse:
    """Liste paginee du personnel."""
    return await admin_service.list_staff(db, page=page, size=size, search=search)


@router.post("/staff", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    data: StaffCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StaffResponse:
    """Cree un nouveau membre du personnel."""
    return await admin_service.create_staff(db, data, created_by=current_user.user_id)


@router.get("/staff/{staff_id}/full", response_model=StaffFullResponse)
async def get_staff_full(
    staff_id: int,
    _: None = require_permission("admin:staff:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Retourne le profil complet d'un membre du personnel."""
    return await admin_service.get_staff_full(db, staff_id)


@router.get("/staff/{staff_id}", response_model=StaffResponse)
async def get_staff(
    staff_id: int,
    _: None = require_permission("admin:staff:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StaffResponse:
    """Retourne un membre du personnel par ID."""
    return await admin_service.get_staff(db, staff_id)


@router.patch("/staff/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: int,
    data: StaffUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StaffResponse:
    """Met a jour un membre du personnel (patch partiel)."""
    return await admin_service.update_staff(db, staff_id, data, updated_by=current_user.user_id)


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(
    staff_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un membre du personnel."""
    await admin_service.delete_staff(db, staff_id, deleted_by=current_user.user_id)


@router.post("/staff/{staff_id}/photo")
async def upload_staff_photo(
    staff_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Upload ou remplace la photo de profil d'un membre du personnel."""
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Format invalide. Accepte: JPEG, PNG, WebP")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"staff_{staff_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 5 Mo)")

    with open(filepath, "wb") as f:
        f.write(content)

    photo_url = f"/uploads/photos/{filename}"
    staff = await admin_service.update_staff_photo(
        db, staff_id, photo_url, updated_by=current_user.user_id
    )
    return {"photo_url": staff.photo_url}


@router.delete("/staff/{staff_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff_photo(
    staff_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime la photo de profil d'un membre du personnel."""
    await admin_service.update_staff_photo(db, staff_id, None, updated_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@router.get("/classes", response_model=ClassListResponse)
async def list_classes(
    level_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:classes:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassListResponse:
    """Liste paginee des classes avec filtres."""
    return await admin_service.list_classes(
        db,
        page=page,
        size=size,
        level_id=level_id,
        academic_year_id=academic_year_id,
        search=search,
    )


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    data: ClassCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:classes:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassResponse:
    """Cree une nouvelle classe."""
    return await admin_service.create_class(db, data, created_by=current_user.user_id)


@router.get("/classes/{class_id}", response_model=ClassResponse)
async def get_class(
    class_id: int,
    _: None = require_permission("admin:classes:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassResponse:
    """Retourne une classe par ID."""
    return await admin_service.get_class(db, class_id)


@router.patch("/classes/{class_id}", response_model=ClassResponse)
async def update_class(
    class_id: int,
    data: ClassUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:classes:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassResponse:
    """Met a jour une classe (patch partiel)."""
    return await admin_service.update_class(db, class_id, data, updated_by=current_user.user_id)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    class_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:classes:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une classe."""
    await admin_service.delete_class(db, class_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@router.get("/subjects", response_model=SubjectListResponse)
async def list_subjects(
    level_id: int | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:subjects:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectListResponse:
    """Liste paginee des matieres."""
    return await admin_service.list_subjects(
        db, page=page, size=size, level_id=level_id, search=search
    )


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    data: SubjectCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:subjects:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectResponse:
    """Cree une nouvelle matiere."""
    return await admin_service.create_subject(db, data, created_by=current_user.user_id)


@router.post(
    "/subjects/duplicate", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED
)
async def duplicate_subject(
    data: SubjectDuplicateRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:subjects:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectResponse:
    """Duplique une matière dans un autre niveau/série."""
    return await admin_service.duplicate_subject(db, data, created_by=current_user.user_id)


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: int,
    _: None = require_permission("admin:subjects:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectResponse:
    """Retourne une matiere par ID."""
    return await admin_service.get_subject(db, subject_id)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: int,
    data: SubjectUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:subjects:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectResponse:
    """Met a jour une matiere (patch partiel)."""
    return await admin_service.update_subject(db, subject_id, data, updated_by=current_user.user_id)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:subjects:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une matiere."""
    await admin_service.delete_subject(db, subject_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Academic Years
# ---------------------------------------------------------------------------


@router.get("/academic-years", response_model=AcademicYearListResponse)
async def list_academic_years(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:academic-years:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearListResponse:
    """Liste paginee des annees academiques."""
    return await admin_service.list_academic_years(db, page=page, size=size)


@router.post(
    "/academic-years",
    response_model=AcademicYearResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_academic_year(
    data: AcademicYearCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearResponse:
    """Cree une nouvelle annee academique."""
    return await admin_service.create_academic_year(db, data, created_by=current_user.user_id)


@router.get("/academic-years/{year_id}", response_model=AcademicYearResponse)
async def get_academic_year(
    year_id: int,
    _: None = require_permission("admin:academic-years:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearResponse:
    """Retourne une annee academique par ID."""
    return await admin_service.get_academic_year(db, year_id)


@router.patch("/academic-years/{year_id}", response_model=AcademicYearResponse)
async def update_academic_year(
    year_id: int,
    data: AcademicYearUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearResponse:
    """Met a jour une annee academique (patch partiel)."""
    return await admin_service.update_academic_year(
        db, year_id, data, updated_by=current_user.user_id
    )


@router.get("/academic-years/current", response_model=AcademicYearResponse)
async def get_current_academic_year(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearResponse:
    """Retourne l'annee academique courante (is_current=True) ou 404."""
    return await admin_service.get_current_academic_year(db)


@router.patch(
    "/academic-years/{year_id}/set-current",
    response_model=AcademicYearResponse,
)
async def set_current_academic_year(
    year_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AcademicYearResponse:
    """Definit une annee academique comme courante (desactive les autres)."""
    return await admin_service.set_current_academic_year(
        db, year_id, updated_by=current_user.user_id
    )


@router.delete("/academic-years/{year_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_academic_year(
    year_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une annee academique."""
    await admin_service.delete_academic_year(db, year_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


@router.get("/levels", response_model=LevelListResponse)
async def list_levels(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:levels:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LevelListResponse:
    """Liste paginee des niveaux."""
    return await admin_service.list_levels(db, page=page, size=size)


@router.post("/levels", response_model=LevelResponse, status_code=status.HTTP_201_CREATED)
async def create_level(
    data: LevelCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:levels:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LevelResponse:
    """Cree un nouveau niveau."""
    return await admin_service.create_level(db, data, created_by=current_user.user_id)


@router.get("/levels/{level_id}", response_model=LevelResponse)
async def get_level(
    level_id: int,
    _: None = require_permission("admin:levels:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LevelResponse:
    """Retourne un niveau par ID."""
    return await admin_service.get_level(db, level_id)


@router.patch("/levels/{level_id}", response_model=LevelResponse)
async def update_level(
    level_id: int,
    data: LevelUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:levels:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> LevelResponse:
    """Met a jour un niveau (patch partiel)."""
    return await admin_service.update_level(db, level_id, data, updated_by=current_user.user_id)


@router.delete("/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_level(
    level_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:levels:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un niveau."""
    await admin_service.delete_level(db, level_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# School Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SchoolSettingsResponse)
async def get_settings(
    _: None = require_permission("admin:academic-years:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SchoolSettingsResponse:
    """Retourne les parametres de l'etablissement."""
    school = await admin_service.get_school_settings(db)
    return SchoolSettingsResponse.model_validate(school)


@router.put("/settings/school-info", response_model=SchoolSettingsResponse)
async def update_school_info(
    data: SchoolInfoUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SchoolSettingsResponse:
    """Met a jour les informations generales de l'etablissement."""
    school = await admin_service.update_school_info(db, data, updated_by=current_user.user_id)
    return SchoolSettingsResponse.model_validate(school)


# ---------------------------------------------------------------------------
# Enrollment Number Pattern (Matricule)
# ---------------------------------------------------------------------------


@router.get("/settings/matricule-preview", response_model=EnrollmentPatternPreview)
async def preview_matricule(
    pattern: str = Query(..., min_length=1, max_length=200),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentPatternPreview:
    """Preview what a matricule would look like with the given pattern."""
    result = await matricule_service.preview_enrollment_number(db, pattern)
    return EnrollmentPatternPreview(**result)


@router.patch("/settings/enrollment-pattern")
async def update_enrollment_pattern(
    data: EnrollmentPatternUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:academic-years:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Update the enrollment number auto-generation pattern."""
    return await admin_service.update_enrollment_pattern(db, data, updated_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


@router.get("/series", response_model=SeriesListResponse)
async def list_series(
    level_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:series:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SeriesListResponse:
    """Liste paginée des séries avec filtre par niveau."""
    return await admin_service.list_series(db, page=page, size=size, level_id=level_id)


@router.post("/series", response_model=SeriesResponse, status_code=status.HTTP_201_CREATED)
async def create_series(
    data: SeriesCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:series:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SeriesResponse:
    """Crée une nouvelle série."""
    return await admin_service.create_series(db, data, created_by=current_user.user_id)


@router.get("/series/{series_id}", response_model=SeriesResponse)
async def get_series(
    series_id: int,
    _: None = require_permission("admin:series:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SeriesResponse:
    """Retourne une série par ID."""
    return await admin_service.get_series(db, series_id)


@router.patch("/series/{series_id}", response_model=SeriesResponse)
async def update_series(
    series_id: int,
    data: SeriesUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:series:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SeriesResponse:
    """Met à jour une série (patch partiel)."""
    return await admin_service.update_series(db, series_id, data, updated_by=current_user.user_id)


@router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(
    series_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:series:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une série."""
    await admin_service.delete_series(db, series_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@router.get("/roles", response_model=RoleListResponse)
async def list_roles(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:roles:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoleListResponse:
    """Liste paginée des rôles avec leurs permissions."""
    return await admin_service.list_roles(db, page=page, size=size)


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:roles:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoleResponse:
    """Crée un nouveau rôle avec des permissions."""
    return await admin_service.create_role(db, data, created_by=current_user.user_id)


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int,
    _: None = require_permission("admin:roles:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoleResponse:
    """Retourne un rôle par ID avec ses permissions."""
    return await admin_service.get_role(db, role_id)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    data: RoleUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:roles:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoleResponse:
    """Met à jour un rôle et ses permissions (patch partiel)."""
    return await admin_service.update_role(db, role_id, data, updated_by=current_user.user_id)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:roles:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un rôle."""
    await admin_service.delete_role(db, role_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    _: None = require_permission("admin:roles:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[PermissionResponse]:
    """Liste toutes les permissions disponibles (pour l'UI d'attribution des rôles)."""
    return await admin_service.list_permissions(db)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms(
    room_type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:rooms:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoomListResponse:
    """Liste paginee des salles avec filtres."""
    return await admin_service.list_rooms(
        db,
        page=page,
        size=size,
        room_type=room_type,
        search=search,
    )


@router.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RoomCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:rooms:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoomResponse:
    """Cree une nouvelle salle."""
    return await admin_service.create_room(db, data, created_by=current_user.user_id)


@router.post("/rooms/batch", response_model=RoomBatchCreateResponse)
async def batch_create_rooms(
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:rooms:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoomBatchCreateResponse:
    """Crée automatiquement une salle pour chaque classe sans salle."""
    return await admin_service.batch_create_rooms_for_classes(
        db,
        created_by=current_user.user_id,
    )


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: int,
    _: None = require_permission("admin:rooms:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoomResponse:
    """Retourne une salle par ID."""
    return await admin_service.get_room(db, room_id)


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    data: RoomUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:rooms:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RoomResponse:
    """Met a jour une salle."""
    return await admin_service.update_room(
        db,
        room_id,
        data,
        updated_by=current_user.user_id,
    )


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:rooms:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une salle."""
    await admin_service.delete_room(db, room_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Parents
# ---------------------------------------------------------------------------


@router.get("/parents", response_model=ParentListResponse)
async def list_parents(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:parents:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentListResponse:
    """Liste paginée des parents avec recherche optionnelle."""
    return await admin_service.list_parents(db, page=page, size=size, search=search)


@router.post("/parents", response_model=ParentResponse, status_code=status.HTTP_201_CREATED)
async def create_parent(
    data: ParentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:parents:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentResponse:
    """Crée un nouveau parent (avec compte utilisateur optionnel)."""
    return await admin_service.create_parent(db, data, created_by=current_user.user_id)


@router.get("/parents/{parent_id}/full", response_model=ParentFullResponse)
async def get_parent_full(
    parent_id: int,
    _: None = require_permission("admin:parents:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Retourne le profil complet d'un parent avec ses enfants."""
    return await admin_service.get_parent_full(db, parent_id)


@router.get("/parents/{parent_id}", response_model=ParentResponse)
async def get_parent(
    parent_id: int,
    _: None = require_permission("admin:parents:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentResponse:
    """Retourne un parent par ID."""
    return await admin_service.get_parent(db, parent_id)


@router.patch("/parents/{parent_id}", response_model=ParentResponse)
async def update_parent(
    parent_id: int,
    data: ParentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:parents:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentResponse:
    """Met à jour un parent (patch partiel)."""
    return await admin_service.update_parent(db, parent_id, data, updated_by=current_user.user_id)


@router.delete("/parents/{parent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parent(
    parent_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:parents:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un parent."""
    await admin_service.delete_parent(db, parent_id, deleted_by=current_user.user_id)


@router.post("/parents/{parent_id}/link/{student_id}", status_code=status.HTTP_201_CREATED)
async def link_parent_to_student(
    parent_id: int,
    student_id: int,
    body: ParentLinkBody,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:parents:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Lie un parent à un élève. Met à jour le type de relation si le lien existe déjà."""
    return await admin_service.link_parent_to_student(
        db, parent_id, student_id, body.relationship_type, linked_by=current_user.user_id
    )


@router.delete("/parents/{parent_id}/link/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_parent_from_student(
    parent_id: int,
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:parents:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime le lien entre un parent et un élève."""
    await admin_service.unlink_parent_from_student(
        db, parent_id, student_id, unlinked_by=current_user.user_id
    )


@router.get("/students/{student_id}/parents")
async def get_student_parents(
    student_id: int,
    _: None = require_permission("admin:parents:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict]:
    """Liste les parents liés à un élève."""
    return await admin_service.get_student_parents(db, student_id)
