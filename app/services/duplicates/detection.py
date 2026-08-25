"""Signaler qu'un élève existe peut-être déjà, avant de le créer une seconde fois.

Trois signaux, du plus sûr au plus incertain :

1. **Le matricule.** Identique, c'est la même personne — on renvoie vers sa
   fiche et vers la réinscription plutôt que vers une création.
2. **L'inscription de l'année en cours.** Si elle existe, même non validée, la
   recréer produit deux dossiers pour un seul élève, et la caisse encaisse sur
   celui que le caissier a sous les yeux.
3. **La ressemblance de l'état civil.** Le filet quand le matricule manque,
   ce qui est le cas de toute famille qui revient sans son papier.

Le service ne bloque rien : il rend ce qu'il a trouvé et laisse l'écran
décider. Bloquer sur une ressemblance ferait refuser un vrai nouvel élève qui
porte le nom de son cousin, et il n'y a pas de recours au guichet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.services.duplicates.similarity import Ressemblance, comparer, normaliser

# Les statuts qui occupent la place : un dossier rejeté ou annulé ne compte
# pas, mais un dossier simplement pas encore validé, si — c'est justement
# celui qu'on risque de recréer parce qu'il ne se voit pas dans les listes.
STATUTS_OCCUPANTS = (
    EnrollmentStatus.PROSPECT,
    EnrollmentStatus.EN_VALIDATION,
    EnrollmentStatus.VALIDE,
)


@dataclass(frozen=True)
class Correspondance:
    """Un élève existant qui pourrait être celui qu'on s'apprête à créer."""

    student_id: int
    last_name: str
    first_name: str
    enrollment_number: str | None
    birth_date: date | None
    birth_place: str | None
    motif: str  # "matricule" | "ressemblance"
    ressemblance: Ressemblance | None
    inscription_annee_courante: dict[str, Any] | None

    @property
    def bloquant(self) -> bool:
        """Un matricule identique ne se discute pas."""
        return self.motif == "matricule"


def _candidats(
    nom: str | None, prenom: str | None, matricule: str | None
) -> Select[tuple[Student]]:
    """Restreindre avant de comparer.

    Comparer la fiche saisie à tous les élèves de l'établissement coûterait une
    lecture complète à chaque frappe. On ne remonte que ceux dont le nom ou le
    prénom partagent un début, plus le matricule exact — le score fait le tri
    ensuite, sur un ensemble réduit.
    """
    conditions = []
    if matricule:
        conditions.append(Student.enrollment_number == matricule)
    for valeur in (nom, prenom):
        racine = normaliser(valeur)[:4]
        if len(racine) >= 3:
            conditions.append(func.lower(Student.last_name).like(f"{racine}%"))
            conditions.append(func.lower(Student.first_name).like(f"{racine}%"))
    if not conditions:
        # Rien d'exploitable : mieux vaut ne rien remonter que tout remonter.
        return select(Student).where(Student.id.is_(None))
    return select(Student).where(or_(*conditions)).limit(200)


async def chercher_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    birth_place: str | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> list[Correspondance]:
    """Les fiches existantes qui pourraient être la même personne, les plus sûres d'abord."""
    resultat = await db.execute(_candidats(last_name, first_name, enrollment_number))
    candidats = list(resultat.scalars().unique())

    saisi = type(
        "Saisi",
        (),
        {
            "last_name": last_name,
            "first_name": first_name,
            "birth_date": birth_date,
            "birth_place": birth_place,
        },
    )()

    trouvees: list[Correspondance] = []
    for existant in candidats:
        if ignorer_student_id is not None and existant.id == ignorer_student_id:
            continue

        meme_matricule = bool(
            enrollment_number
            and existant.enrollment_number
            and existant.enrollment_number.strip().lower() == enrollment_number.strip().lower()
        )
        r = comparer(saisi, existant)
        if not meme_matricule and not r.a_signaler:
            continue

        trouvees.append(
            Correspondance(
                student_id=existant.id,
                last_name=existant.last_name,
                first_name=existant.first_name,
                enrollment_number=existant.enrollment_number,
                birth_date=existant.birth_date,
                birth_place=existant.birth_place,
                motif="matricule" if meme_matricule else "ressemblance",
                ressemblance=None if meme_matricule else r,
                inscription_annee_courante=await _inscription_de_l_annee(
                    db, existant.id, academic_year_id
                ),
            )
        )

    trouvees.sort(
        key=lambda c: (c.motif != "matricule", -(c.ressemblance.score if c.ressemblance else 1.0))
    )
    return trouvees


async def _inscription_de_l_annee(
    db: AsyncSession, student_id: int, academic_year_id: int | None
) -> dict[str, Any] | None:
    """L'inscription de l'élève pour l'année visée, **même non validée**.

    C'est la moitié utile du signalement : un dossier en attente n'apparaît
    pas là où le secrétariat regarde, et c'est celui-là qu'on recrée.
    """
    if academic_year_id is None:
        return None
    ligne = await db.execute(
        select(Enrollment)
        .options(selectinload(Enrollment.class_))
        .where(
            Enrollment.student_id == student_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.in_([s.value for s in STATUTS_OCCUPANTS]),
        )
        .limit(1)
    )
    inscription = ligne.scalars().first()
    if inscription is None:
        return None
    return {
        "enrollment_id": inscription.id,
        "status": inscription.status,
        "class_name": inscription.class_.name if inscription.class_ else None,
    }
