"""Socle partagé des actes de vie scolaire : contexte élève, trimestre, sceau.

Les quatre documents posent les mêmes questions avant d'imprimer quoi que ce
soit : qui est l'élève, dans quelle classe, sur quelle année, et à quel
trimestre on se trouve. Les factoriser ici évite que la convocation et le
billet d'annulation de zéro répondent différemment le même jour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Trimester
from app.models.enrollment import Enrollment
from app.models.user import Student, User
from app.repositories.user_repository import get_user_full_name
from app.services._document_verification_helper import (
    DOCUMENT_RENDER_VERSION,
    VerificationPayload,
    build_verification,
)
from app.services._school_settings_helper import load_school_settings_for_pdf


@dataclass(frozen=True)
class StudentContext:
    """Tout ce qu'un acte doit savoir de l'élève avant d'être composé."""

    student: Student
    enrollment: Enrollment
    class_name: str
    academic_year_id: int
    academic_year_name: str
    school_settings: dict[str, Any]

    def student_payload(self) -> dict[str, Any]:
        """Projection de l'élève telle que les générateurs PDF la consomment."""
        return {
            "first_name": self.student.first_name,
            "last_name": self.student.last_name,
            "genre": self.student.genre.value
            if hasattr(self.student.genre, "value")
            else self.student.genre,
            "enrollment_number": self.student.enrollment_number,
            "previous_school": self.student.previous_school,
            "transfer_decision_number": self.student.transfer_decision_number,
        }

    @property
    def student_name(self) -> str:
        return f"{self.student.first_name} {self.student.last_name}".strip()


async def load_student_context(db: AsyncSession, student_id: int) -> StudentContext:
    """Charge l'élève et son inscription valide de l'année courante.

    Un acte de vie scolaire s'adresse à un élève inscrit : sans inscription
    valide, on refuse plutôt que d'imprimer une classe vide qu'un enseignant
    devrait deviner.
    """
    student = await db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student", student_id)

    stmt = (
        select(Enrollment)
        .where(Enrollment.student_id == student_id, Enrollment.status == "valide")
        .options(selectinload(Enrollment.class_), selectinload(Enrollment.academic_year))
        .order_by(Enrollment.created_at.desc())
        .limit(1)
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise BusinessValidationError(
            "Aucune inscription valide trouvée pour cet élève. "
            "Vérifiez qu'il est inscrit à l'année scolaire courante."
        )

    return StudentContext(
        student=student,
        enrollment=enrollment,
        class_name=enrollment.class_.name if enrollment.class_ else "",
        academic_year_id=enrollment.academic_year_id,
        academic_year_name=enrollment.academic_year.name if enrollment.academic_year else "",
        school_settings=await load_school_settings_for_pdf(db),
    )


async def current_class_names(db: AsyncSession, student_ids: set[int]) -> dict[int, str]:
    """Classe courante de chaque élève, en une requête plutôt qu'une par ligne.

    Les registres affichent la classe à côté du nom : la charger ligne par
    ligne transformerait un écran de trente convocations en trente et une
    requêtes.
    """
    if not student_ids:
        return {}
    stmt = (
        select(Enrollment)
        .where(Enrollment.student_id.in_(student_ids), Enrollment.status == "valide")
        .options(selectinload(Enrollment.class_))
        .order_by(Enrollment.created_at.desc())
    )
    names: dict[int, str] = {}
    for enrollment in (await db.execute(stmt)).scalars().all():
        # Requête triée du plus récent au plus ancien : la première inscription
        # rencontrée pour un élève est bien la sienne aujourd'hui.
        names.setdefault(enrollment.student_id, enrollment.class_.name if enrollment.class_ else "")
    return names


async def resolve_trimester(
    db: AsyncSession, academic_year_id: int, on_day: date | None = None
) -> int:
    """Trimestre couvrant `on_day`, à défaut le dernier commencé, à défaut 1.

    Le registre des convocations est consulté « par trimestre » : demander à
    l'éducateur de le saisir à chaque convocation serait une question dont le
    calendrier scolaire connaît déjà la réponse.
    """
    day = on_day or date.today()
    stmt = (
        select(Trimester)
        .where(Trimester.academic_year_id == academic_year_id)
        .order_by(Trimester.order_no)
    )
    trimesters = list((await db.execute(stmt)).scalars().all())
    if not trimesters:
        return 1
    for trimester in trimesters:
        if trimester.start_date <= day <= trimester.end_date:
            return trimester.order_no
    started = [t for t in trimesters if t.start_date <= day]
    return started[-1].order_no if started else trimesters[0].order_no


async def actor_name(db: AsyncSession, user_id: int) -> str | None:
    """Nom lisible de l'agent qui a émis un acte, pour le registre."""
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
            selectinload(User.parent_profile),
        )
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        return None
    first_name, last_name = get_user_full_name(user)
    return f"{last_name} {first_name}".strip() or user.email


async def issue_act_seal(
    db: AsyncSession,
    *,
    document_type: str,
    ref_prefix: str,
    context: StudentContext,
    issued_at: datetime,
    source_data: dict[str, Any],
    act_id: int | None,
) -> VerificationPayload:
    """Crée le sceau numérique d'un acte qui sort de l'établissement.

    La référence est calculée ici pour qu'elle corresponde exactement à ce qui
    est signé puis imprimé — un écart entre les deux rendrait la vérification
    publique incompréhensible pour la personne qui tient le papier.

    Elle porte l'identifiant de l'acte, comme le bulletin porte son trimestre.
    La lignée de sceaux est indexée sur (type de document, référence), et
    finaliser une révision périme toutes les précédentes de la même référence :
    sans cet identifiant, le second billet d'annulation de zéro d'un élève
    invaliderait le premier, et l'enseignant qui scanne le papier du trimestre 1
    lirait « document remplacé ». `act_id` vaut None pour les actes qui n'ont
    pas de registre — la demande de dossier scolaire — où une émission
    corrigée doit effectivement remplacer la précédente.

    Le matricule est exigé : sans lui, tous les élèves non matriculés
    partageaient la même référence, donc la même lignée. Un rendu échoué
    laissait alors un sceau en attente qui bloquait le guichet entier pendant
    cinq minutes, pour tout le monde.
    """
    matricule = (context.student.enrollment_number or "").strip()
    if not matricule:
        raise BusinessValidationError(
            f"L'élève {context.student_name} n'a pas de matricule. "
            "Renseignez-le sur sa fiche avant d'éditer cet acte : la référence du "
            "document et sa vérification en ligne reposent dessus."
        )
    suffix = f"-{act_id}" if act_id is not None else ""
    reference = f"{ref_prefix}-{issued_at.year}-{matricule}{suffix}"
    return await build_verification(
        db,
        document_type=document_type,
        reference=reference,
        student_name=context.student_name,
        class_name=context.class_name,
        academic_year=context.academic_year_name,
        student_id=context.student.id,
        issued_at=issued_at,
        source_data={**source_data, "template_version": DOCUMENT_RENDER_VERSION},
    )
