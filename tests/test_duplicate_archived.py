"""Une fiche mise à la corbeille ne doit pas remonter comme doublon.

La corbeille promet qu'archiver « retire la fiche de tous les écrans sans rien
détruire ». Cet écran-ci est le plus mauvais endroit où rompre cette promesse :
la détection oriente le secrétariat vers la fiche trouvée plutôt que vers une
création. Une fiche archivée qui remonte enverrait donc vers un dossier annulé,
avec un bandeau « inscription valide cette année » qui ne l'est plus.

Le filtre est global, posé sur la session dans `app/main.py`. La requête de
doublons ne le nomme nulle part — elle en hérite. C'est justement ce qui rend
ce test nécessaire : rien dans le module de détection ne rappelle que cette
protection existe, donc rien n'empêche une future version de la contourner avec
`INCLUDE_ARCHIVED` ou une requête montée à la main.
"""

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.services.duplicates.detection import find_duplicates


class _Pont:
    """Donne l'allure d'une `AsyncSession` a une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def session_filtree() -> Iterator[Session]:
    """Une session qui se comporte comme en production : corbeille filtrée.

    Le filtre n'est pas branché ici : `tests/conftest.py` importe `app.main`,
    qui l'enregistre pour tout le processus de test. Le brancher une seconde
    fois ferait croire que ce test le porte, alors qu'il vérifie justement le
    câblage de `app/main.py` en même temps que la requête.
    """
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        archive = datetime(2026, 1, 1)
        s.add_all(
            [
                AcademicYear(
                    id=1,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                Student(
                    id=1,
                    last_name="KOUASSI",
                    first_name="Aya",
                    enrollment_number="ECER0001",
                    archived_at=archive,
                    archive_reason="fiche creee en double",
                ),
                Student(
                    id=2,
                    last_name="TRAORE",
                    first_name="Fatou",
                    enrollment_number="ECER0002",
                ),
                # Eleve vivant, inscription annulee puis mise a la
                # corbeille : c'est le cas du troisieme axe.
                Student(
                    id=3,
                    last_name="BAMBA",
                    first_name="Ibrahim",
                    enrollment_number="ECER0003",
                ),
                Enrollment(
                    id=2,
                    student_id=3,
                    class_id=1,
                    academic_year_id=1,
                    status=EnrollmentStatus.VALIDE.value,
                    archived_at=archive,
                ),
                Enrollment(
                    id=1,
                    student_id=1,
                    class_id=1,
                    academic_year_id=1,
                    status=EnrollmentStatus.VALIDE.value,
                    archived_at=archive,
                ),
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_une_fiche_a_la_corbeille_ne_remonte_pas(session_filtree: Session) -> None:
    """La fiche archivée, son matricule et son inscription restent invisibles.

    Les trois axes de la détection sont interrogés : la ressemblance de l'état
    civil, le matricule exact, et l'inscription occupante de l'année. Aucun ne
    doit ramener une fiche mise à la corbeille.
    """
    par_le_nom = await find_duplicates(
        _Pont(session_filtree), last_name="KOUASSI", first_name="Aya", academic_year_id=1
    )
    assert par_le_nom.matches == [], "une fiche archivée ne se signale pas par son nom"

    par_le_matricule = await find_duplicates(
        _Pont(session_filtree),
        last_name="KOUASSI",
        first_name="Aya",
        enrollment_number="ECER0001",
        academic_year_id=1,
    )
    assert par_le_matricule.matches == [], "ni par son matricule"


@pytest.mark.asyncio
async def test_une_fiche_vivante_remonte_toujours(session_filtree: Session) -> None:
    """Le contrôle qui empêche le test précédent de passer pour rien.

    Sans lui, une détection qui ne trouverait plus jamais personne rendrait les
    deux assertions ci-dessus vertes tout en étant complètement cassée.
    """
    trouve = await find_duplicates(
        _Pont(session_filtree), last_name="TRAORE", first_name="Fatou", academic_year_id=1
    )
    assert [c.enrollment_number for c in trouve.matches] == ["ECER0002"]


@pytest.mark.asyncio
async def test_une_inscription_a_la_corbeille_ne_se_dit_pas_ouverte(
    session_filtree: Session,
) -> None:
    """Le troisième axe : l'inscription occupante de l'année.

    L'élève est vivant, son inscription a été annulée puis mise à la corbeille.
    Il doit remonter comme doublon — c'est bien la même personne — mais SANS le
    bandeau « inscription valide cette année », qui enverrait la secrétaire
    vers une réinscription au lieu d'une inscription, et ferait croire à une
    place déjà prise.

    Le premier test de ce fichier ne pouvait pas atteindre cet axe : sa fixture
    archive l'élève ET son inscription, donc l'élève disparaît avant qu'on
    puisse regarder son inscription.
    """
    reponse = await find_duplicates(
        _Pont(session_filtree), last_name="BAMBA", first_name="Ibrahim", academic_year_id=1
    )

    trouve = [c for c in reponse.matches if c.enrollment_number == "ECER0003"]
    assert trouve, "l'élève lui-même est vivant : il doit se signaler"
    assert trouve[0].current_year_enrollment is None, (
        "une inscription à la corbeille n'occupe plus la place"
    )
