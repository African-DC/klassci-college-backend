---
paths:
  - "app/routers/**/*.py"
  - "app/schemas/**/*.py"
---

# Règles API Design — KLASSCI Backend

## Structure des Endpoints

```
GET    /api/v1/{resource}           ← liste paginée
POST   /api/v1/{resource}           ← création
GET    /api/v1/{resource}/{id}      ← détail
PUT    /api/v1/{resource}/{id}      ← mise à jour complète
PATCH  /api/v1/{resource}/{id}      ← mise à jour partielle
DELETE /api/v1/{resource}/{id}      ← suppression

# Sous-ressources
GET    /api/v1/enrollments/{id}/payments
POST   /api/v1/enrollments/{id}/payments
```

## Format des Réponses

```python
# Succès — objet unique
{"data": {"id": 1, "status": "valide", ...}}

# Succès — liste paginée
{
    "data": [...],
    "total": 100,
    "page": 1,
    "per_page": 20,
    "pages": 5
}

# Erreur métier
{"detail": "Fee structure not configured for this academic year", "code": "FEE_STRUCTURE_MISSING"}

# Erreur validation
{"detail": [{"loc": ["body", "email"], "msg": "Invalid email", "type": "value_error"}]}
```

## Router Structure

```python
# app/routers/enrollments.py
from fastapi import APIRouter, Depends, Query
from app.core.dependencies import require_permission, get_tenant_db, get_current_user

router = APIRouter(prefix="/enrollments", tags=["enrollments"])

@router.get("/", response_model=PaginatedResponse[EnrollmentResponse])
async def list_enrollments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    class_id: int | None = Query(None),
    _: None = Depends(require_permission("enrollments:view")),
    db: AsyncSession = Depends(get_tenant_db),
):
    service = EnrollmentService(db)
    enrollments, total = await service.list(page=page, per_page=per_page, status=status)
    return {"data": enrollments, "total": total, "page": page, "per_page": per_page}

@router.post("/", response_model=DataResponse[EnrollmentResponse], status_code=201)
async def create_enrollment(
    data: EnrollmentCreate,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_permission("enrollments:create")),
    db: AsyncSession = Depends(get_tenant_db),
):
    service = EnrollmentService(db)
    enrollment = await service.create(data, created_by=current_user.id)
    return {"data": enrollment}
```

## Versioning

- Toujours préfixer avec `/api/v1/`
- Si breaking change → créer `/api/v2/` en gardant v1 fonctionnel
- Documenter les dépréciations dans les headers de réponse

## OpenAPI / Docs

```python
# Documenter chaque endpoint
@router.post(
    "/",
    response_model=DataResponse[EnrollmentResponse],
    status_code=201,
    summary="Create a new enrollment",
    description="Creates a new student enrollment. Requires at least one payment to move to 'en_validation' status.",
    responses={
        400: {"description": "Fee structure not configured"},
        403: {"description": "Permission denied"},
    }
)
```
