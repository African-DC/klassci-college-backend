"""Ce que les chemins de création d'inscription partagent.

Trois petites lectures que `enrollment_service` et `enrollment_with_student`
appellent tous deux : le profil à retenir, le nom affichable de l'élève et
l'année courante. Elles vivent ici pour que ni l'un ni l'autre n'importe
l'autre.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear
from app.schemas.enrollment import EnrollmentCreate, EnrollmentWithStudentCreate
from app.services import enrollment_history


async def profil_a_retenir(
    db: AsyncSession,
    data: EnrollmentCreate | EnrollmentWithStudentCreate,
    student_id: int,
    academic_year_id: int,
) -> bool | None:
    """Le profil de l'inscription : celui du formulaire, ou celui qu'on déduit.

    Le corps sait dire trois choses, et il faut les distinguer toutes les
    trois :

    - `true` / `false` : le guichet a tranché, il l'emporte toujours. C'est
      lui qui a le dossier sous les yeux, la suggestion n'est qu'une aide.
    - `is_new_student: null` **envoyé** : le guichet dit explicitement qu'il ne
      tranche pas. On enregistre ce vide tel quel. Déduire ici démentirait
      l'écran, qui vient de promettre « non tranché ».
    - champ **absent** du corps : personne ne s'est prononcé, on lit
      l'historique. Si l'école ne l'a pas déclaré exploitable, la déduction
      rend `None` à son tour plutôt que d'inventer un montant.

    D'où la lecture de `model_fields_set` et non un test sur la valeur : `None`
    est ici une valeur métier, pas une absence.
    """
    if "is_new_student" in data.model_fields_set:
        return data.is_new_student
    return await enrollment_history.deduce_new_student(db, student_id, academic_year_id)


def nom_eleve(enrollment: object) -> str:
    """Le nom affichable de l'élève, ou son matricule s'il manque."""
    student = getattr(enrollment, "student", None)
    if student is None:
        return "Un élève"
    parts = [getattr(student, "last_name", ""), getattr(student, "first_name", "")]
    nom = " ".join(p for p in parts if p).strip()
    return nom or getattr(student, "enrollment_number", "") or "Un élève"


async def get_current_academic_year(db: AsyncSession) -> AcademicYear:
    """Retourne l'annee scolaire courante ou leve une erreur metier."""
    stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    result = await db.execute(stmt)
    year = result.scalar_one_or_none()
    if not year:
        raise BusinessValidationError(
            "Aucune annee academique courante definie. "
            "Veuillez configurer l'annee courante dans les parametres."
        )
    return year
