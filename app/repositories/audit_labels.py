"""Nommer, par lot, les fiches citées par une page du journal.

Une ligne de journal porte un type et un identifiant : « class 12 ». Pour un
humain, c'est « 6e B ». Ce module fait cette traduction pour une page entière,
avec une requête par type d'entité présent sur la page, jamais une par ligne.

Chaque type est décrit une fois : la requête qui ramène ses lignes, et la
façon d'en faire un libellé. Les requêtes s'écrivent sur les classes du modèle
et nomment chaque colonne, que le formateur lit par son nom (`r.prenom`), pas
par sa position. Elles ne lisent que des colonnes scalaires et des jointures
explicites : aucun chargement paresseux, donc pas de `MissingGreenlet`.

**Les fiches archivées sont lues exprès.** Le filtre d'archivage
(`core/archive_filter.py`) les cache au reste de l'application ; le journal,
lui, doit encore pouvoir les nommer. On le lève par `include_archived`, et on
remonte l'archivage avec le nom, pour que l'écran ne propose pas d'ouvrir une
fiche que les autres pages refusent d'afficher.

`personnel` marque les types dont le libellé est le nom d'une personne. Le
service décide qui a le droit de les lire ; ce module se contente de le dire.
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.archive_filter import INCLUDE_ARCHIVED
from app.models.academic import AcademicYear, Class, Level, Room, Series, Subject
from app.models.attendance import AttendanceContext, TeacherSessionAttendance
from app.models.cash_session import CashSession
from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, FeeCategory, FeeVariant, OptionalFeeOption, Payment
from app.models.grade import Bulletin, CouncilMinutes, Evaluation, Grade
from app.models.permission import Role
from app.models.school_life import ParentSummons
from app.models.timetable import TimetableSlot
from app.models.user import Parent, StaffProfile, Student, TeacherProfile, User

logger = logging.getLogger(__name__)

#: `DayOfWeek` est stocké en anglais (« monday ») : l'écran le dit en français.
JOURS = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
    "sunday": "dimanche",
}


def _jour(valeur: object) -> str | None:
    brut = str(getattr(valeur, "value", valeur) or "").lower()
    return JOURS.get(brut, brut or None)


def _nom(prenom: object, nom: object) -> str:
    return f"{prenom or ''} {nom or ''}".strip()


def _joindre(*morceaux: object) -> str | None:
    texte = " · ".join(str(m) for m in morceaux if m not in (None, ""))
    return texte or None


def _date(valeur: object) -> str | None:
    return valeur.strftime("%d/%m/%Y") if isinstance(valeur, date) else None


def _heure(valeur: object) -> str | None:
    return valeur.strftime("%Hh%M") if isinstance(valeur, time) else None


def _montant(valeur: object) -> str | None:
    # Le franc CFA n'a pas de centimes : la partie entière est le montant.
    if valeur is None:
        return None
    return f"{int(Decimal(str(valeur))):,} FCFA".replace(",", " ")


def _trimestre(valeur: object) -> str | None:
    return f"T{valeur}" if valeur not in (None, "") else None


@dataclass(frozen=True, slots=True)
class Fiche:
    """Ce que le journal sait d'une fiche retrouvée."""

    nom: str | None
    archivee: bool = False


@dataclass(frozen=True, slots=True)
class Libelle:
    """Comment nommer un type d'entité : sa requête, sa mise en forme.

    La requête rend une colonne `id`, une colonne `archived_at` pour les
    modèles archivables, puis les colonnes que lit le formateur.
    """

    requete: Callable[[Sequence[int]], Select[Any]]
    former: Callable[[Any], str | None]
    personnel: bool = False


def _colonne(modele: Any, colonne: str = "name") -> Libelle:
    return Libelle(
        requete=lambda ids: select(
            modele.id.label("id"), getattr(modele, colonne).label("nom")
        ).where(modele.id.in_(ids)),
        former=lambda r: str(r.nom) if r.nom else None,
    )


def _personne(modele: Any, *, matricule: bool = False) -> Libelle:
    def requete(ids: Sequence[int]) -> Select[Any]:
        colonnes = [
            modele.id.label("id"),
            modele.archived_at.label("archived_at"),
            modele.first_name.label("prenom"),
            modele.last_name.label("nom"),
        ]
        if matricule:
            colonnes.append(modele.enrollment_number.label("matricule"))
        return select(*colonnes).where(modele.id.in_(ids))

    return Libelle(
        requete=requete,
        former=lambda r: _joindre(_nom(r.prenom, r.nom), r.matricule if matricule else None),
        personnel=True,
    )


LIBELLES: dict[str, Libelle] = {
    # Données de référence : aucun nom de personne.
    "class": _colonne(Class),
    "level": _colonne(Level),
    "series": _colonne(Series),
    "subject": _colonne(Subject),
    "room": _colonne(Room),
    "academic_year": _colonne(AcademicYear),
    "fee_category": _colonne(FeeCategory),
    "optional_fee_option": _colonne(OptionalFeeOption),
    "role": _colonne(Role),
    "cash_session": Libelle(
        requete=lambda ids: select(
            CashSession.id.label("id"), CashSession.business_date.label("jour")
        ).where(CashSession.id.in_(ids)),
        former=lambda r: _joindre("Caisse du", _date(r.jour)),
    ),
    "enrollment_fee": Libelle(
        requete=lambda ids: (
            select(EnrollmentFee.id.label("id"), FeeCategory.name.label("frais"))
            .select_from(EnrollmentFee)
            .outerjoin(FeeCategory, FeeCategory.id == EnrollmentFee.fee_category_id)
            .where(EnrollmentFee.id.in_(ids))
        ),
        former=lambda r: r.frais or None,
    ),
    "fee_variant": Libelle(
        requete=lambda ids: (
            select(
                FeeVariant.id.label("id"),
                FeeCategory.name.label("frais"),
                FeeVariant.amount.label("montant"),
            )
            .select_from(FeeVariant)
            .outerjoin(FeeCategory, FeeCategory.id == FeeVariant.fee_category_id)
            .where(FeeVariant.id.in_(ids))
        ),
        former=lambda r: _joindre(r.frais, _montant(r.montant)),
    ),
    "evaluation": Libelle(
        requete=lambda ids: (
            select(
                Evaluation.id.label("id"),
                Evaluation.title.label("titre"),
                Class.name.label("classe"),
            )
            .select_from(Evaluation)
            .outerjoin(Class, Class.id == Evaluation.class_id)
            .where(Evaluation.id.in_(ids))
        ),
        former=lambda r: _joindre(r.titre, r.classe),
    ),
    "timetable_slot": Libelle(
        requete=lambda ids: (
            select(
                TimetableSlot.id.label("id"),
                Class.name.label("classe"),
                Subject.name.label("matiere"),
                TimetableSlot.day.label("jour"),
                TimetableSlot.start_time.label("debut"),
            )
            .select_from(TimetableSlot)
            .outerjoin(Class, Class.id == TimetableSlot.class_id)
            .outerjoin(Subject, Subject.id == TimetableSlot.subject_id)
            .where(TimetableSlot.id.in_(ids))
        ),
        former=lambda r: _joindre(r.classe, r.matiere, _jour(r.jour), _heure(r.debut)),
    ),
    "attendance_session": Libelle(
        requete=lambda ids: (
            select(
                AttendanceContext.id.label("id"),
                AttendanceContext.date.label("jour"),
                Class.name.label("classe"),
            )
            .select_from(AttendanceContext)
            .outerjoin(
                Class,
                and_(
                    AttendanceContext.entity_type == "class",
                    Class.id == AttendanceContext.context_id,
                ),
            )
            .where(AttendanceContext.id.in_(ids))
        ),
        former=lambda r: _joindre("Appel", r.classe, _date(r.jour)),
    ),
    "council_minutes": Libelle(
        requete=lambda ids: (
            select(
                CouncilMinutes.id.label("id"),
                Class.name.label("classe"),
                CouncilMinutes.trimester.label("trimestre"),
            )
            .select_from(CouncilMinutes)
            .outerjoin(Class, Class.id == CouncilMinutes.class_id)
            .where(CouncilMinutes.id.in_(ids))
        ),
        former=lambda r: _joindre("Conseil", r.classe, _trimestre(r.trimestre)),
    ),
    # Noms de personnes.
    "student": _personne(Student, matricule=True),
    "teacher": _personne(TeacherProfile),
    "staff": _personne(StaffProfile),
    "parent": _personne(Parent),
    # Le lien parent-élève est journalisé sous l'identifiant du parent.
    "parent_student": _personne(Parent),
    "user": Libelle(
        requete=lambda ids: select(User.id.label("id"), User.email.label("courriel")).where(
            User.id.in_(ids)
        ),
        former=lambda r: r.courriel or None,
        personnel=True,
    ),
    "enrollment": Libelle(
        requete=lambda ids: (
            select(
                Enrollment.id.label("id"),
                Enrollment.archived_at.label("archived_at"),
                Student.first_name.label("prenom"),
                Student.last_name.label("nom"),
                Class.name.label("classe"),
            )
            .select_from(Enrollment)
            .outerjoin(Student, Student.id == Enrollment.student_id)
            .outerjoin(Class, Class.id == Enrollment.class_id)
            .where(Enrollment.id.in_(ids))
        ),
        former=lambda r: _joindre(_nom(r.prenom, r.nom), r.classe),
        personnel=True,
    ),
    "payment": Libelle(
        requete=lambda ids: (
            select(
                Payment.id.label("id"),
                Payment.amount.label("montant"),
                Payment.student_name_snapshot.label("nom_fige"),
                Student.first_name.label("prenom"),
                Student.last_name.label("nom"),
            )
            .select_from(Payment)
            .outerjoin(Enrollment, Enrollment.id == Payment.enrollment_id)
            .outerjoin(Student, Student.id == Enrollment.student_id)
            .where(Payment.id.in_(ids))
        ),
        # Le nom recopié sur le versement fait foi quand la fiche est partie.
        former=lambda r: _joindre(_montant(r.montant), _nom(r.prenom, r.nom) or r.nom_fige),
        personnel=True,
    ),
    "grade": Libelle(
        requete=lambda ids: (
            select(
                Grade.id.label("id"),
                Student.first_name.label("prenom"),
                Student.last_name.label("nom"),
                Subject.name.label("matiere"),
                Evaluation.title.label("titre"),
            )
            .select_from(Grade)
            .outerjoin(Student, Student.id == Grade.student_id)
            .outerjoin(Evaluation, Evaluation.id == Grade.evaluation_id)
            .outerjoin(Subject, Subject.id == Evaluation.subject_id)
            .where(Grade.id.in_(ids))
        ),
        former=lambda r: _joindre(_nom(r.prenom, r.nom), r.matiere or r.titre),
        personnel=True,
    ),
    "bulletin": Libelle(
        requete=lambda ids: (
            select(
                Bulletin.id.label("id"),
                Student.first_name.label("prenom"),
                Student.last_name.label("nom"),
                Bulletin.trimester.label("trimestre"),
            )
            .select_from(Bulletin)
            .outerjoin(Student, Student.id == Bulletin.student_id)
            .where(Bulletin.id.in_(ids))
        ),
        former=lambda r: _joindre(_nom(r.prenom, r.nom), _trimestre(r.trimestre)),
        personnel=True,
    ),
    "parent_summons": Libelle(
        requete=lambda ids: (
            select(
                ParentSummons.id.label("id"),
                Student.first_name.label("prenom"),
                Student.last_name.label("nom"),
                ParentSummons.summons_date.label("jour"),
            )
            .select_from(ParentSummons)
            .outerjoin(Student, Student.id == ParentSummons.student_id)
            .where(ParentSummons.id.in_(ids))
        ),
        former=lambda r: _joindre(_nom(r.prenom, r.nom), _date(r.jour)),
        personnel=True,
    ),
    "teacher_session_attendance": Libelle(
        requete=lambda ids: (
            select(
                TeacherSessionAttendance.id.label("id"),
                TeacherProfile.first_name.label("prenom"),
                TeacherProfile.last_name.label("nom"),
                TeacherSessionAttendance.date.label("jour"),
            )
            .select_from(TeacherSessionAttendance)
            .outerjoin(TeacherProfile, TeacherProfile.id == TeacherSessionAttendance.teacher_id)
            .where(TeacherSessionAttendance.id.in_(ids))
        ),
        former=lambda r: _joindre(_nom(r.prenom, r.nom), _date(r.jour)),
        personnel=True,
    ),
}


async def names_by_type(
    db: AsyncSession, wanted: dict[str, Iterable[int]]
) -> dict[str, dict[int, Fiche]]:
    """Pour chaque type demandé, les fiches retrouvées, archivées comprises.

    Une fiche absente du résultat n'existe plus. Une requête qui échoue ne
    coûte que les noms de son type : la page s'affiche quand même, avec des
    numéros, parce que les lignes du journal sont la vérité et les noms leur
    habillage. L'échec est journalisé, pas avalé.
    """
    trouve: dict[str, dict[int, Fiche]] = {}
    for entity_type, ids in wanted.items():
        spec = LIBELLES.get(entity_type)
        uniques = sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)})
        if spec is None or not uniques:
            continue
        # Construire, exécuter et mettre en forme sont couverts ensemble : une
        # valeur inattendue dans un formateur coûte les noms de son type, pas
        # la page. L'échec reste journalisé.
        try:
            requete = spec.requete(uniques).execution_options(**{INCLUDE_ARCHIVED: True})
            lignes = (await db.execute(requete)).all()
            trouve[entity_type] = {
                int(r.id): Fiche(
                    nom=spec.former(r),
                    archivee=getattr(r, "archived_at", None) is not None,
                )
                for r in lignes
            }
        except (SQLAlchemyError, ArithmeticError, AttributeError, TypeError, ValueError):
            logger.exception("Journal d'audit : noms introuvables pour le type %s", entity_type)
    return trouve
