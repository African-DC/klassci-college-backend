---
paths:
  - "app/models/**/*.py"
  - "app/repositories/**/*.py"
  - "alembic/**/*.py"
---

# Règles Base de Données — KLASSCI Backend

## Conventions Schéma MySQL

```python
# app/models/base.py
from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

## Types de Colonnes Obligatoires

| Données | Type SQLAlchemy | Type MySQL |
|---------|----------------|------------|
| PK | `BigInteger, autoincrement=True` | `BIGINT UNSIGNED AUTO_INCREMENT` |
| FK | `BigInteger` | `BIGINT UNSIGNED` |
| Montants | `Numeric(15, 2)` | `DECIMAL(15,2)` — jamais Float |
| Statuts | `Enum(...)` | `ENUM(...)` |
| Textes courts | `String(255)` | `VARCHAR(255)` |
| Textes longs | `Text` | `TEXT` |
| Booléens | `Boolean` | `TINYINT(1)` |
| JSON | `JSON` | `JSON` |

## Modèle Example

```python
# app/models/enrollment.py
from sqlalchemy import String, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

class Enrollment(Base, TimestampMixin):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("students.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("classes.id"), nullable=False)
    academic_year_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academic_years.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("prospect", "en_validation", "valide", "rejete", name="enrollment_status"),
        nullable=False,
        default="prospect"
    )

    # Relations
    student: Mapped["Student"] = relationship(back_populates="enrollments")
    class_: Mapped["Class"] = relationship(back_populates="enrollments")
```

## Migrations Alembic

```python
# Toujours explicite — jamais laisser autogenerate gérer les FKs sans vérifier
def upgrade() -> None:
    op.create_table(
        "enrollments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Enum("prospect", "en_validation", "valide", "rejete"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_enrollments_student_id", "enrollments", ["student_id"])
    op.create_index("idx_enrollments_status", "enrollments", ["status"])

def downgrade() -> None:
    op.drop_table("enrollments")
```

## Repository Pattern

```python
# app/repositories/enrollment_repository.py
class EnrollmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, enrollment_id: int) -> Enrollment | None:
        stmt = select(Enrollment).where(Enrollment.id == enrollment_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_class(
        self,
        class_id: int,
        academic_year_id: int,
        page: int = 1,
        per_page: int = 20
    ) -> tuple[list[Enrollment], int]:
        base_stmt = select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id
        )
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar()
        stmt = base_stmt.offset((page - 1) * per_page).limit(per_page)
        result = await self.db.execute(stmt)
        return result.scalars().all(), total
```

## Transactions Multi-Write

```python
# Toujours une transaction explicite pour plusieurs écritures liées
async def create_enrollment_with_fees(self, data: EnrollmentCreate) -> Enrollment:
    async with self.db.begin():  # transaction automatiquement commit/rollback
        enrollment = Enrollment(**data.model_dump())
        self.db.add(enrollment)
        await self.db.flush()  # obtenir l'ID sans commit

        # Appliquer les frais
        fee_variants = await self._get_applicable_fee_variants(enrollment)
        for variant in fee_variants:
            fee = EnrollmentFee(enrollment_id=enrollment.id, fee_variant_id=variant.id)
            self.db.add(fee)

    return enrollment
```

## Index Obligatoires

Créer un index sur toute colonne utilisée dans un WHERE fréquent :
- `*_id` (toutes les FK)
- `status`
- `academic_year_id`
- `created_at` (si filtrage par date)
- `email` (unique sur users)
