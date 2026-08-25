"""La détection appelée pour de vrai, sur une base réelle.

Le cas qui a motivé tout ceci : 45 élèves de 2025-2026 doivent des arriérés.
S'ils reviennent et que le secrétariat recrée une fiche faute de retrouver le
matricule, l'ardoise reste attachée à l'ancienne et personne ne la réclame.

Ces tests montent un vrai schéma SQLite et interrogent la vraie fonction.
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
from app.services.duplicates.detection import chercher_doublons


class _Pont:
    """Une `AsyncSession` de façade sur une session synchrone réelle."""

    def __init__(self, session: Session) -> None:
        self._s = session

    async def execute(self, statement: object) -> object:
        return self._s.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def db() -> Iterator[Session]:
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all([
            AcademicYear(id=1, name="2025-2026", start_date=date(2025, 9, 8),
                         end_date=date(2026, 6, 30), is_current=False),
            AcademicYear(id=2, name="2026-2027", start_date=date(2026, 9, 14),
                         end_date=date(2027, 7, 30), is_current=True),
            Level(id=1, name="3eme", order=4),
            Class(id=1, name="3eme 2", level_id=1),
            # Trois élèves du fichier réel des arriérés.
            Student(id=1, last_name="KOUASSI", first_name="Aya marie adelaide",
                    enrollment_number="ECER0882"),
            Student(id=2, last_name="KOUASSI", first_name="David", enrollment_number="ECER0864"),
            Student(id=3, last_name="COULIBALY", first_name="Souleymane ben junior",
                    enrollment_number="ECER0734"),
        ])
        s.add(Enrollment(id=1, student_id=1, class_id=1, academic_year_id=2,
                         status=EnrollmentStatus.PROSPECT.value))
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_le_matricule_identique_est_bloquant(db: Session) -> None:
    trouves = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya", enrollment_number="ECER0882"
    )
    assert [t.motif for t in trouves][:1] == ["matricule"]
    assert trouves[0].bloquant is True


@pytest.mark.asyncio
async def test_sans_matricule_la_ressemblance_retrouve_la_fiche(db: Session) -> None:
    # La famille revient sans son papier : c'est le cas qui fabrique les
    # doublons, et celui que le score doit rattraper.
    trouves = await chercher_doublons(
        _Pont(db), last_name="Coulibaly", first_name="souleymane ben junior"
    )
    assert [t.student_id for t in trouves] == [3]
    assert trouves[0].motif == "ressemblance"
    assert trouves[0].ressemblance.juge_sur_peu is True


@pytest.mark.asyncio
async def test_deux_kouassi_distincts_ne_sont_pas_confondus(db: Session) -> None:
    trouves = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name="David")
    assert [t.student_id for t in trouves] == [2], "l'autre KOUASSI a été signalé à tort"


@pytest.mark.asyncio
async def test_une_inscription_non_validee_est_signalee(db: Session) -> None:
    # Le cœur de la demande : un dossier en attente ne se voit pas dans les
    # listes, et c'est celui-là qu'on recrée.
    trouves = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya marie adelaide",
        enrollment_number="ECER0882", academic_year_id=2,
    )
    inscription = trouves[0].inscription_annee_courante
    assert inscription is not None
    assert inscription["status"] == EnrollmentStatus.PROSPECT.value
    assert inscription["class_name"] == "3eme 2"


@pytest.mark.asyncio
async def test_sans_annee_on_ne_pretend_pas_connaitre_l_inscription(db: Session) -> None:
    trouves = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya marie adelaide",
        enrollment_number="ECER0882",
    )
    assert trouves[0].inscription_annee_courante is None


@pytest.mark.asyncio
async def test_un_nouvel_eleve_ne_declenche_rien(db: Session) -> None:
    trouves = await chercher_doublons(_Pont(db), last_name="ZOUZOUA", first_name="Emmanuella")
    assert trouves == []


@pytest.mark.asyncio
async def test_la_fiche_modifiee_ne_se_signale_pas_elle_meme(db: Session) -> None:
    trouves = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="David",
        enrollment_number="ECER0864", ignorer_student_id=2,
    )
    assert trouves == []
