"""Quelle inscription « occupe la place » de l'année en cours.

Le bandeau « inscription déjà ouverte cette année » décide de ce que fait la
secrétaire : réinscrire, ou inscrire. Se tromper l'envoie deux fois du mauvais
côté.

Un dossier rejeté ou annulé n'occupe rien — la famille est repartie, la place
est libre, et signaler une inscription qui n'existe plus ferait refuser une
inscription légitime. Un dossier prospect ou en validation, lui, occupe : c'est
justement celui qu'on risque de recréer, parce qu'il ne se voit pas encore dans
les listes.

Ces cinq décisions vivaient dans un tuple que la docstring de `detection.py`
explique en une phrase, et qu'aucun test ne parcourait : la seule inscription
des autres fixtures est en prospect. On pouvait donc y ajouter « annulé », ou
en retirer « validé », sans qu'un seul test bronche.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.services.duplicates.detection import find_duplicates

ANNEE = 1


class _Pont:
    """Donne l'allure d'une `AsyncSession` a une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def session() -> Iterator[Session]:
    """Un élève par statut d'inscription, tous sur l'année en cours."""
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
            ]
        )
        for numero, statut in enumerate(EnrollmentStatus, start=1):
            s.add(
                Student(
                    id=numero,
                    last_name="KOUASSI",
                    first_name=f"Eleve{numero}",
                    enrollment_number=f"ECER{numero:04d}",
                )
            )
            s.add(
                Enrollment(
                    id=numero,
                    student_id=numero,
                    class_id=1,
                    academic_year_id=ANNEE,
                    status=statut.value,
                )
            )
        s.commit()
        yield s


@pytest.mark.parametrize(
    ("statut", "occupe"),
    [
        (EnrollmentStatus.PROSPECT, True),
        (EnrollmentStatus.EN_VALIDATION, True),
        (EnrollmentStatus.VALIDE, True),
        (EnrollmentStatus.REJETE, False),
        (EnrollmentStatus.ANNULE, False),
    ],
)
@pytest.mark.asyncio
async def test_seuls_les_dossiers_vivants_occupent_la_place(
    session: Session, statut: EnrollmentStatus, occupe: bool
) -> None:
    """Les cinq décisions, une par une.

    Chaque élève de la fixture porte un statut différent ; la recherche les
    ramène tous, et on regarde lequel se déclare occupant.
    """
    numero = list(EnrollmentStatus).index(statut) + 1
    reponse = await find_duplicates(
        _Pont(session),
        last_name="KOUASSI",
        first_name=f"Eleve{numero}",
        academic_year_id=ANNEE,
    )

    trouve = [c for c in reponse.matches if c.student_id == numero]
    assert trouve, f"l'élève au statut {statut.value} doit remonter comme doublon"

    inscription = trouve[0].current_year_enrollment
    if occupe:
        assert inscription is not None, (
            f"un dossier « {statut.value} » occupe la place : c'est celui qu'on "
            "risque de recréer sans le voir"
        )
        assert inscription.status == statut.value
    else:
        assert inscription is None, (
            f"un dossier « {statut.value} » n'occupe plus rien : le signaler "
            "ferait refuser une inscription légitime"
        )
