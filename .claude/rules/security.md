---
paths:
  - "app/**/*.py"
---

# Règles Sécurité — KLASSCI Backend

## Authentification JWT

```python
# Toujours vérifier le tenant_id dans le token
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_tenant_db)
) -> User:
    payload = decode_jwt(token)
    if payload.get("tenant_id") != get_current_tenant_id():
        raise HTTPException(status_code=401, detail="Invalid tenant")
    user = await user_repo.get_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return user
```

## Permissions Dynamiques — Jamais Hardcodées

```python
# INTERDIT — permission hardcodée
if current_user.role == "admin":
    ...

# CORRECT — permission depuis la DB
async def require_permission(permission_slug: str):
    async def dependency(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db)
    ):
        has_perm = await check_user_permission(db, current_user.id, permission_slug)
        if not has_perm:
            raise HTTPException(status_code=403, detail="Permission denied")
    return Depends(dependency)

# Usage
@router.post("/enrollments")
async def create_enrollment(
    data: EnrollmentCreate,
    _: None = Depends(require_permission("enrollments:create")),
    db: AsyncSession = Depends(get_tenant_db),
):
    ...
```

## Ce qui vérifie cette règle

```bash
python scripts/check_permissions.py
```

Deux contrôles, tenus par un hook `pre-commit` et par la CI :

- **Toute route est gardée.** Une route sans `require_permission` doit être
  déclarée dans `ROUTES_PUBLIQUES`, avec la raison qui la rend ouverte. Cette
  liste est de la documentation autant qu'une exception : elle répond à
  « qu'est-ce qui est ouvert sur cette API », sans relire trois cents signatures.
- **Aucun rôle ne décide d'un accès** dans `app/routers/`, `core/dependencies.py`
  et `core/middleware.py`. Ailleurs, comparer un rôle sert à choisir la bonne
  table de profil — c'est du polymorphisme, et l'interdire noierait le contrôle
  de faux positifs jusqu'à ce que quelqu'un le désactive.

**Ce qu'il ne fait pas** : vérifier que le droit demandé est le *bon*. Rien ne
sait que le tableau des soldes relève de `payments:read:all` et non de
`payments:read` — c'est un jugement, il se prend en revue. Le contrôle garantit
qu'un droit est demandé, pas qu'il est le bon.

## Audit Log Obligatoire

```python
# Sur toutes les mutations sensibles : paiements, notes, inscriptions,
# modifications de frais, changements de rôles/permissions
await audit_log(
    db=db,
    user_id=current_user.id,
    entity_type="payment",
    entity_id=payment.id,
    action="create",
    old_values=None,
    new_values=payment_data.model_dump(),
)
```

## Validation des Inputs

```python
# Toujours valider via Pydantic AVANT toute opération DB
# Pas de request.json() ou dict() directement

# INTERDIT
data = await request.json()
enrollment = Enrollment(**data)  # aucune validation

# CORRECT
async def create_enrollment(
    data: EnrollmentCreate,  # Pydantic valide automatiquement
    ...
):
    enrollment = await service.create(data)
```

## Variables d'Environnement

```python
# app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    class Config:
        env_file = ".env"

settings = Settings()
```

## Interdictions

```python
# INTERDIT — secrets dans le code
SECRET_KEY = "my-secret-key-123"

# INTERDIT — SQL brut avec interpolation
await db.execute(f"SELECT * FROM users WHERE email = '{email}'")

# INTERDIT — afficher les détails d'erreur en production
raise HTTPException(status_code=500, detail=str(e))  # expose le stacktrace

# CORRECT — message générique
raise HTTPException(status_code=500, detail="Internal server error")
# Et logger l'erreur complète en interne
logger.exception("Unexpected error in create_enrollment")
```
