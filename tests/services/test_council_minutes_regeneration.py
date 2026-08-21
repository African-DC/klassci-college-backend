"""Regénérer un procès-verbal de conseil de classe déjà établi.

L'écran du conseil propose de relancer la génération : c'est le geste normal
quand une note a été corrigée après la tenue du conseil. Le service commence
alors par détruire le PV précédent avant d'en réécrire un.

Tant que la relation vers les décisions ne laissait pas la clé étrangère faire
son travail, SQLAlchemy détachait les décisions en mettant leur
`council_minutes_id` à NULL avant de supprimer le PV, sur une colonne qui ne
l'accepte pas. Le premier conseil passait, le second échouait sur une erreur
d'intégrité, et le directeur des études restait avec un PV périmé.

Les tests tournent sur SQLite, avec l'intégrité référentielle activée : c'est
elle qui rend la cascade observable, exactement comme MySQL la porte.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import BigInteger, Integer, MetaData, create_engine, event, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — enregistre toutes les tables sur `Base`
from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.grade import CouncilMinutes, CouncilStudentDecision
from app.models.user import Student
from app.repositories import council_repository as repo

ANNEE = 1
NIVEAU = 1
CLASSE = 1
TRIMESTRE = 1
EFFECTIF = 3


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone.

    Le dépôt n'utilise que ces trois gestes ; les envelopper évite d'ajouter un
    pilote asynchrone à la seule fin de faire tourner des tests.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: Any) -> Any:
        return self.session.execute(statement)

    async def delete(self, instance: Any) -> None:
        self.session.delete(instance)

    async def flush(self) -> None:
        self.session.flush()


def _sqlite_schema() -> MetaData:
    """Le schéma du modèle, transposé pour SQLite.

    SQLite ne numérote automatiquement que les colonnes « INTEGER PRIMARY
    KEY » : les `BIGINT` du modèle refuseraient tout INSERT sans identifiant.
    On travaille sur une copie, jamais sur les tables que les autres tests
    lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    for table in miroir.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    return miroir


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve, une classe de trois élèves, un conseil déjà tenu."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection: Any, _record: Any) -> None:
        # Sans ce réglage, SQLite ignore les clés étrangères : la cascade que
        # le test observe n'existerait pas et il passerait pour de mauvaises
        # raisons.
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _sqlite_schema().create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Level(id=NIVEAU, name="6eme", order=1),
                AcademicYear(
                    id=ANNEE,
                    name="2025-2026",
                    start_date=date(2025, 9, 15),
                    end_date=date(2026, 7, 10),
                    is_current=True,
                ),
                Class(id=CLASSE, name="6eme A", level_id=NIVEAU),
            ]
        )
        session.add_all(
            [
                Student(id=index, first_name=f"Eleve{index}", last_name="Traore")
                for index in range(1, EFFECTIF + 1)
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _tenir_le_conseil(bridge: _AsyncBridge) -> CouncilMinutes:
    """Écrit un PV et la décision de chaque élève, comme le fait le service."""
    conseil = CouncilMinutes(
        class_id=CLASSE,
        academic_year_id=ANNEE,
        trimester=TRIMESTRE,
        main_teacher_name="M. Kouassi",
        director_name="Mme Diallo",
    )
    bridge.session.add(conseil)
    bridge.session.flush()
    for index in range(1, EFFECTIF + 1):
        bridge.session.add(
            CouncilStudentDecision(
                council_minutes_id=conseil.id,
                student_id=index,
                average=Decimal("12.50"),
                rank=index,
                absence_count=index,
                auto_decision="admis",
            )
        )
    bridge.session.flush()
    return conseil


def _decisions_restantes(bridge: _AsyncBridge) -> int:
    return len(bridge.session.execute(select(CouncilStudentDecision)).scalars().all())


@pytest.mark.asyncio
async def test_un_pv_deja_etabli_se_detruit_pour_etre_regenere(db: _AsyncBridge) -> None:
    """Le geste que l'écran propose : regénérer un conseil déjà tenu."""
    _tenir_le_conseil(db)
    assert _decisions_restantes(db) == EFFECTIF

    existant = await repo.get_council_minutes(db, CLASSE, TRIMESTRE, ANNEE)  # type: ignore[arg-type]
    assert existant is not None

    await repo.delete_council_minutes(db, existant)  # type: ignore[arg-type]

    assert db.session.execute(select(CouncilMinutes)).scalars().all() == []


@pytest.mark.asyncio
async def test_les_decisions_partent_avec_le_pv_sans_rester_orphelines(db: _AsyncBridge) -> None:
    """La cascade est portée par la base : aucune décision ne survit au PV.

    Si la relation cessait de laisser la clé étrangère décider, ces lignes
    seraient soit détachées, et l'écriture refusée, soit laissées derrière
    elles et le PV suivant compterait deux fois chaque élève.
    """
    _tenir_le_conseil(db)
    existant = await repo.get_council_minutes(db, CLASSE, TRIMESTRE, ANNEE)  # type: ignore[arg-type]
    assert existant is not None

    await repo.delete_council_minutes(db, existant)  # type: ignore[arg-type]

    assert _decisions_restantes(db) == 0


@pytest.mark.asyncio
async def test_le_conseil_suivant_repart_sur_une_ardoise_nette(db: _AsyncBridge) -> None:
    """Deux générations de suite, et l'effectif du second PV est le bon."""
    _tenir_le_conseil(db)
    premier = await repo.get_council_minutes(db, CLASSE, TRIMESTRE, ANNEE)  # type: ignore[arg-type]
    assert premier is not None
    await repo.delete_council_minutes(db, premier)  # type: ignore[arg-type]

    _tenir_le_conseil(db)

    second = await repo.get_council_minutes(db, CLASSE, TRIMESTRE, ANNEE)  # type: ignore[arg-type]
    assert second is not None
    assert len(second.decisions) == EFFECTIF


def test_la_base_emporte_bien_les_decisions_avec_le_pv(db: _AsyncBridge) -> None:
    """Le modèle s'en remet à la base : encore faut-il qu'elle cascade.

    Les tests précédents ne prouveraient rien si la colonne était en RESTRICT :
    la suppression échouerait pour une tout autre raison. On vérifie donc que
    la base elle-même emporte les décisions quand le PV disparaît.
    """
    conseil = _tenir_le_conseil(db)
    table = CouncilMinutes.__table__
    db.session.execute(table.delete().where(table.c.id == conseil.id))

    assert _decisions_restantes(db) == 0
