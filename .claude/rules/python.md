---
paths:
  - "app/**/*.py"
  - "tests/**/*.py"
---

# Règles Python — KLASSCI Backend

## Async Obligatoire

```python
# INTERDIT — synchrone
def get_user(db: Session, user_id: int) -> User:
    return db.query(User).filter(User.id == user_id).first()

# CORRECT — async
async def get_user(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
```

## SQLAlchemy 2.0 Style

```python
# INTERDIT — style 1.x
db.query(User).filter(User.email == email).first()

# CORRECT — style 2.0
stmt = select(User).where(User.email == email)
result = await db.execute(stmt)
user = result.scalar_one_or_none()

# CORRECT — insert
stmt = insert(User).values(email=email, hashed_password=hashed)
await db.execute(stmt)
await db.commit()

# CORRECT — update
stmt = update(User).where(User.id == user_id).values(is_active=False)
await db.execute(stmt)
await db.commit()
```

## Pydantic v2

```python
# CORRECT — modèles Pydantic v2
from pydantic import BaseModel, EmailStr, field_validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

## Structure Service

```python
# app/services/enrollment_service.py
class EnrollmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EnrollmentRepository(db)

    async def create_enrollment(
        self,
        data: EnrollmentCreate,
        created_by: int
    ) -> Enrollment:
        # 1. Valider (vérifier que la structure de frais existe)
        await self._validate_fee_structure(data.class_id, data.academic_year_id)
        # 2. Créer
        enrollment = await self.repo.create(data, created_by)
        # 3. Audit log
        await audit_log(self.db, "enrollment", enrollment.id, "create", None, enrollment)
        return enrollment
```

## Gestion des Erreurs

```python
# Exceptions custom dans app/core/exceptions.py
class KlassciException(HTTPException):
    pass

class NotFoundError(KlassciException):
    def __init__(self, entity: str, id: int):
        super().__init__(status_code=404, detail=f"{entity} with id {id} not found")

class PermissionError(KlassciException):
    def __init__(self, action: str):
        super().__init__(status_code=403, detail=f"Permission denied: {action}")

# Usage dans les services
async def get_enrollment(self, enrollment_id: int) -> Enrollment:
    enrollment = await self.repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment", enrollment_id)
    return enrollment
```

## Interdictions

```python
# INTERDIT — print() en production
print("user created")  # Utiliser logger.info()

# INTERDIT — except trop large sans re-raise
try:
    result = await do_something()
except Exception:
    pass  # Avale silencieusement l'erreur

# INTERDIT — import *
from app.models import *

# INTERDIT — logique dans __init__.py
```
