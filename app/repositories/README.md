# app/repositories/ — Acces Base de Donnees

Un fichier par modele. Contient uniquement des requetes SQL, zero logique metier.

## Convention

```python
class EnrollmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: int) -> Enrollment | None:
        stmt = select(Enrollment).where(Enrollment.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, page: int = 1, per_page: int = 20) -> tuple[list[Enrollment], int]:
        count_stmt = select(func.count()).select_from(Enrollment)
        total = (await self.db.execute(count_stmt)).scalar()
        stmt = select(Enrollment).offset((page - 1) * per_page).limit(per_page)
        items = (await self.db.execute(stmt)).scalars().all()
        return items, total
```

## Regles

- SQLAlchemy 2.0 uniquement (`select()`, pas `db.query()`)
- Toujours `async def`
- Utiliser `selectinload`/`joinedload` pour eviter les N+1
- Toujours paginer les listes
- Jamais de logique metier ici
