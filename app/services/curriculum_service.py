"""Service curriculum — résolution des matières enseignées par classe.

Source unique de vérité pour la question : *« quelles matières sont enseignées
dans cette classe ? »*. Le prédicat SQLAlchemy est défini une seule fois et
réutilisé par le filtre liste (`GET /admin/subjects?class_id=N`) et par la
validation de cohérence (`POST /evaluations` avec une paire (class_id,
subject_id) incohérente). Aucune duplication possible entre la query SQL et
une éventuelle vérification Python — le prédicat *est* le contrat.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class, Subject


def subject_for_class_predicate(class_obj: Class) -> ColumnElement[bool]:
    """Construit la clause WHERE qui matche les matières enseignées dans `class_obj`.

    Sémantique :
    - Un `Subject.level_id` à NULL = matière enseignée à tous les niveaux (ex : EPS).
    - Un `Subject.series_id` à NULL = matière enseignée dans toutes les séries
      du niveau (ex : Mathématiques en Terminale, qui existe en A, C, D).
    - Sinon le `level_id` (et le `series_id` si présent côté Subject) doit
      matcher exactement la classe.

    Le prédicat est partagé entre `subjects_for_class()` et
    `validate_subject_class_pair()` pour garantir que le filtre côté liste
    et la validation côté écriture appliquent exactement la même règle.
    """
    return and_(
        or_(Subject.level_id.is_(None), Subject.level_id == class_obj.level_id),
        or_(Subject.series_id.is_(None), Subject.series_id == class_obj.series_id),
    )


async def _get_class_or_404(db: AsyncSession, class_id: int) -> Class:
    class_obj = await db.get(Class, class_id)
    if class_obj is None:
        raise NotFoundError("Class", class_id)
    return class_obj


async def subjects_for_class(db: AsyncSession, class_id: int) -> list[Subject]:
    """Retourne les matières enseignées dans la classe `class_id`.

    Inclut les matières globales (`level_id` NULL) et série-agnostiques
    (`series_id` NULL). Triées par nom pour un rendu prévisible côté UI.
    """
    class_obj = await _get_class_or_404(db, class_id)
    stmt = (
        select(Subject).where(subject_for_class_predicate(class_obj)).order_by(Subject.name.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def validate_subject_class_pair(db: AsyncSession, class_id: int, subject_id: int) -> None:
    """Lève une 422 si la matière n'est pas enseignée dans cette classe.

    Utilise la même clause `subject_for_class_predicate` que la liste — donc
    si une matière apparaît dans le Select côté UI, elle passe la validation
    ici sans drift possible.
    """
    class_obj = await _get_class_or_404(db, class_id)
    stmt = select(Subject.id).where(
        Subject.id == subject_id,
        subject_for_class_predicate(class_obj),
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise BusinessValidationError("Cette matière n'est pas enseignée dans cette classe.")
