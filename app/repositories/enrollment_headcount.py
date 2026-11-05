"""Qui compte dans « élèves inscrits » : une seule définition pour tous les écrans.

Recette du 2026-11-05 : le même établissement affichait 817 élèves inscrits sur
le tableau de bord et sur la page des classes, 716 dans l'arbre des classes et
dans les statistiques DREN. Les deux premiers additionnaient les inscriptions de
toutes les années, validées ou non, archivées comprises.

Un élève inscrit est une inscription validée, non archivée, de l'année en
cours. Les dossiers en validation et les prospects se comptent à part : ils
ne sont pas encore dans l'effectif qu'on déclare à la DRENA.
"""

from sqlalchemy import ColumnElement, and_, select

from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment, EnrollmentStatus


def current_year_enrollment(*statuses: EnrollmentStatus) -> ColumnElement[bool]:
    """Inscriptions non archivées de l'année en cours, aux statuts donnés."""
    current_year = select(AcademicYear.id).where(AcademicYear.is_current.is_(True))
    return and_(
        Enrollment.academic_year_id.in_(current_year.scalar_subquery()),
        Enrollment.archived_at.is_(None),
        Enrollment.status.in_(statuses),
    )


def headcount_for_year(academic_year_id: int) -> ColumnElement[bool]:
    """L'effectif d'une année donnée : inscriptions validées et non archivées."""
    return and_(
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.archived_at.is_(None),
        Enrollment.status == EnrollmentStatus.VALIDE,
    )


def counted_in_headcount() -> ColumnElement[bool]:
    """L'effectif de l'année en cours : tableau de bord et page des classes."""
    return current_year_enrollment(EnrollmentStatus.VALIDE)
