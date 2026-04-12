"""Router admin — CRUD endpoints pour les entités de base."""

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
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
    SchoolInfoUpdate,
    SchoolSettingsResponse,
    LevelCreate,
    LevelListResponse,
    LevelResponse,
    LevelUpdate,
    StaffCreate,
    StaffFullResponse,
    StaffListResponse,
    StaffResponse,
    StaffUpdate,
    StudentCreate,
    StudentEnrollmentFeeListResponse,
    StudentFullResponse,
    UserAccountUpdate,
    StudentListResponse,
    StudentResponse,
    StudentUpdate,
    SubjectCreate,
    SubjectListResponse,
    SubjectResponse,
    SubjectUpdate,
    TeacherCreate,
    TeacherFullResponse,
    TeacherListResponse,
    TeacherResponse,
    TeacherUpdate,
)
from app.services import admin_service
from app.services import matricule_service

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
    return await admin_service.update_student(
        db, student_id, data, updated_by=current_user.user_id
    )


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
    student = await admin_service.update_student_photo(db, student_id, photo_url, updated_by=current_user.user_id)
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
    return await admin_service.update_teacher(
        db, teacher_id, data, updated_by=current_user.user_id
    )


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher(
    teacher_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un enseignant."""
    await admin_service.delete_teacher(db, teacher_id, deleted_by=current_user.user_id)


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
    return await admin_service.update_staff(
        db, staff_id, data, updated_by=current_user.user_id
    )


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(
    staff_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:staff:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un membre du personnel."""
    await admin_service.delete_staff(db, staff_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@router.get("/classes", response_model=ClassListResponse)
async def list_classes(
    level_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:classes:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassListResponse:
    """Liste paginee des classes avec filtres."""
    return await admin_service.list_classes(
        db, page=page, size=size, level_id=level_id, academic_year_id=academic_year_id
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
    return await admin_service.update_class(
        db, class_id, data, updated_by=current_user.user_id
    )


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
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:subjects:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectListResponse:
    """Liste paginee des matieres."""
    return await admin_service.list_subjects(db, page=page, size=size, level_id=level_id)


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    data: SubjectCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:subjects:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectResponse:
    """Cree une nouvelle matiere."""
    return await admin_service.create_subject(db, data, created_by=current_user.user_id)


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
    return await admin_service.update_subject(
        db, subject_id, data, updated_by=current_user.user_id
    )


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
    return await admin_service.update_level(
        db, level_id, data, updated_by=current_user.user_id
    )


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
    return await admin_service.update_enrollment_pattern(
        db, data, updated_by=current_user.user_id
    )
