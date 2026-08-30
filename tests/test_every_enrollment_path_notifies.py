"""Chaque manière de créer une inscription doit prévenir la caisse.

Le défaut trouvé le 2026-08-25, en créant une inscription sur la démo après
avoir déployé la chaîne : la notification n'apparaissait pas. Le service a
**deux** fonctions de création. `create_enrollment` appelait bien la chaîne ;
`create_enrollment_with_student` — celle que le formulaire « Nouvelle
inscription » emprunte, où la secrétaire saisit l'élève et son inscription
d'un seul geste — commitait puis retournait sans rien prévenir.

Autrement dit, la chaîne était muette précisément sur le chemin qui sert.

Le test précédent vérifiait la diffusion, en aval : il ne pouvait pas voir
qu'un appelant manquait. Celui-ci part de l'autre bout — il énumère les
fonctions publiques de création et appelle chacune pour de vrai, sur une base
réelle. Une troisième porte ajoutée demain sans prévenir la caisse fera
échouer ce fichier.
"""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.user import User
from app.schemas.enrollment import EnrollmentCreate, EnrollmentWithStudentCreate
from app.services import enrollment_service

SECRETAIRE = 1


class _AsyncBridge:
    """Une `AsyncSession` de façade posée sur une session synchrone réelle."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def refresh(self, instance: object, *a: object, **k: object) -> None:
        self._session.refresh(instance)

    def begin_nested(self) -> Any:
        return _TransactionImbriquee(self._session)


class _TransactionImbriquee:
    """`async with db.begin_nested()` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._transaction: Any = None

    async def __aenter__(self) -> Any:
        self._transaction = self._session.begin_nested()
        return self._transaction

    async def __aexit__(self, type_erreur: object, *_: object) -> bool:
        if type_erreur is not None:
            self._transaction.rollback()
            return False
        self._transaction.commit()
        return False


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=SECRETAIRE, email="sophie@ecole.ci", hashed_password="x", role="staff"),
                AcademicYear(
                    id=1,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=True,
                ),
                Level(id=1, name="6ème", order=1),
                Class(id=1, name="6ème A", level_id=1),
            ]
        )
        session.commit()
        yield session


@pytest.fixture()
def prevenus(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Les inscriptions pour lesquelles la caisse a été prévenue."""
    vus: list[int] = []

    async def _faux(db: object, *, enrollment_id: int, **kw: object) -> None:
        vus.append(enrollment_id)

    monkeypatch.setattr(
        enrollment_service.enrollment_notifications,
        "prevenir_qu_il_faut_encaisser",
        _faux,
    )
    return vus


@pytest.mark.asyncio
async def test_le_formulaire_complet_previent_la_caisse(db: Session, prevenus: list[int]) -> None:
    """`/enrollments/with-student` : le chemin du formulaire, celui qui manquait."""
    reponse = await enrollment_service.create_enrollment_with_student(
        _AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentWithStudentCreate(
            first_name="Aminata",
            last_name="Traoré",
            class_id=1,
            academic_year_id=1,
            # Obligatoire : sans motif configuré, le service refuse et a raison.
            enrollment_number="26000001A",
        ),
        created_by=SECRETAIRE,
    )
    assert prevenus == [reponse.id]


@pytest.mark.asyncio
async def test_l_inscription_d_un_eleve_existant_previent_aussi(
    db: Session, prevenus: list[int]
) -> None:
    """`/enrollments` : le chemin déjà couvert, gardé pour que la paire reste vraie."""
    cree = await enrollment_service.create_enrollment_with_student(
        _AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentWithStudentCreate(
            first_name="Kouadio",
            last_name="Yao",
            class_id=1,
            academic_year_id=1,
            enrollment_number="26000002B",
        ),
        created_by=SECRETAIRE,
    )
    prevenus.clear()

    db.execute(
        __import__("sqlalchemy").text("DELETE FROM enrollments WHERE id = :i"), {"i": cree.id}
    )
    db.commit()

    reponse = await enrollment_service.create_enrollment(
        _AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentCreate(student_id=cree.student_id, class_id=1, academic_year_id=1),
        created_by=SECRETAIRE,
    )
    assert prevenus == [reponse.id]
