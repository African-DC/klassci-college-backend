# app/routers/ — Endpoints HTTP

Un fichier par domaine. Chaque router est enregistré dans `app/main.py`.

## Convention

```python
router = APIRouter(prefix="/enrollments", tags=["enrollments"])

@router.get("/", response_model=PaginatedResponse[EnrollmentResponse])
async def list_enrollments(
    _: None = Depends(require_permission("enrollments:view")),
    db: AsyncSession = Depends(get_tenant_db),
):
    service = EnrollmentService(db)
    return await service.list(...)
```

## Règles absolues

- Jamais de logique métier dans les routers
- Toujours `require_permission("module:action")` sur chaque endpoint protégé
- Format réponse uniforme via `DataResponse` et `PaginatedResponse`

## Endpoints standard

```
GET    /resource          liste paginee
POST   /resource          creer
GET    /resource/{id}     detail
PUT    /resource/{id}     modifier
DELETE /resource/{id}     supprimer
```
