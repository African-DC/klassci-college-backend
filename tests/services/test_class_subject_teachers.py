"""Enseignant retenu par classe et par matière : résolution, enregistrement, heures.

Vraie session asynchrone sur SQLite en mémoire : ce qui est lu est ce qui est
enregistré. Les matières passent par le vrai service de répartition, qui purge
les choix devenus orphelins.
"""

import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import Integer, MetaData, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class, Level, Series, Subject
from app.models.audit import AuditLog
from app.models.class_subject_teacher import ClassSubjectTeacher
from app.models.user import TeacherProfile
from app.schemas.class_subject_teachers import (
    ClassSubjectTeacherAssignment,
    ClassSubjectTeachersUpdate,
)
from app.services import class_subject_teacher_service as svc
from app.services import subject_teachers as subject_svc
from app.services import teacher_workload as workload

NIVEAU_6E = 1
NIVEAU_5E = 2
CLASSE_6A = 10
CLASSE_6B = 11
CLASSE_5A = 12
KOUASSI, TRAORE, YAO = 1, 2, 3
ACTEUR = 1
TABLES = (
    "levels",
    "series",
    "classes",
    "subjects",
    "teacher_profiles",
    "subject_teachers",
    "class_subject_teachers",
    "audit_logs",
)


def _schema() -> list[Any]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    tables = []
    for nom in TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Deux niveaux, trois classes (deux en 6e), trois enseignants."""
    moteur = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: MetaData().create_all(c, tables=_schema()))

    async with AsyncSession(moteur, expire_on_commit=False) as db:
        db.add_all(
            [
                Level(id=NIVEAU_6E, name="6e", order=1),
                Level(id=NIVEAU_5E, name="5e", order=2),
                Class(id=CLASSE_6A, name="6eme A", level_id=NIVEAU_6E),
                Class(id=CLASSE_6B, name="6eme B", level_id=NIVEAU_6E),
                Class(id=CLASSE_5A, name="5eme A", level_id=NIVEAU_5E),
                TeacherProfile(id=KOUASSI, user_id=101, first_name="Jean", last_name="Kouassi"),
                TeacherProfile(id=TRAORE, user_id=102, first_name="Awa", last_name="Traoré"),
                TeacherProfile(id=YAO, user_id=103, first_name="Sophie", last_name="Yao"),
            ]
        )
        await db.commit()
        yield db
    await moteur.dispose()


async def _matiere(
    db: AsyncSession, nom: str, niveau: int, enseignants: list[int], heures: int = 2
) -> Subject:
    matiere = Subject(name=nom, level_id=niveau, hours_per_week=heures)
    db.add(matiere)
    await db.flush()
    await subject_svc.set_subject_teachers(db, matiere, enseignants)
    await db.commit()
    db.expunge_all()
    return matiere


async def _choisir(db: AsyncSession, classe: int, matiere: int, enseignant: int | None) -> None:
    await svc.save_class_teachers(
        db,
        classe,
        [ClassSubjectTeacherAssignment(subject_id=matiere, teacher_id=enseignant)],
        actor=ACTEUR,
    )
    db.expunge_all()


async def _entree(db: AsyncSession, classe: int, matiere: int) -> svc.ClassSubjectTeacherEntry:
    cls = await db.get(Class, classe)
    assert cls is not None
    entries = await svc.resolve_class_teachers(db, cls)
    return next(e for e in entries if e.subject.id == matiere)


@pytest.mark.asyncio
async def test_un_seul_enseignant_retenu_est_resolu_sans_choix(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI])

    entree = await _entree(session, CLASSE_6A, maths.id)

    assert entree.source == "single"
    assert entree.resolved_teacher_id == KOUASSI
    assert entree.resolved_name == "Jean Kouassi"


@pytest.mark.asyncio
async def test_plusieurs_enseignants_sans_choix_ne_resolvent_rien(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])

    entree = await _entree(session, CLASSE_6A, maths.id)

    assert entree.source == "none"
    assert entree.resolved_teacher_id is None


@pytest.mark.asyncio
async def test_choix_explicite_l_emporte_et_se_fait_par_classe(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])
    await _choisir(session, CLASSE_6A, maths.id, KOUASSI)
    await _choisir(session, CLASSE_6B, maths.id, TRAORE)

    a = await _entree(session, CLASSE_6A, maths.id)
    b = await _entree(session, CLASSE_6B, maths.id)

    assert (a.source, a.resolved_teacher_id) == ("explicit", KOUASSI)
    assert (b.source, b.resolved_teacher_id) == ("explicit", TRAORE)
    assert await svc.class_teacher_names(session, CLASSE_6A) == {maths.id: "Jean Kouassi"}
    assert await svc.class_teacher_names(session, CLASSE_6B) == {maths.id: "Awa Traoré"}


@pytest.mark.asyncio
async def test_choix_devient_invalide_quand_l_enseignant_quitte_la_matiere(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])
    await _choisir(session, CLASSE_6A, maths.id, TRAORE)

    attached = await session.get(Subject, maths.id)
    assert attached is not None
    await subject_svc.set_subject_teachers(session, attached, [KOUASSI])
    await session.commit()
    session.expunge_all()

    entree = await _entree(session, CLASSE_6A, maths.id)
    orphelins = (
        (
            await session.execute(
                select(ClassSubjectTeacher).where(ClassSubjectTeacher.subject_id == maths.id)
            )
        )
        .scalars()
        .all()
    )
    assert orphelins == []
    assert (entree.source, entree.resolved_teacher_id) == ("single", KOUASSI)


@pytest.mark.asyncio
async def test_enregistrement_refuse_un_enseignant_non_retenu(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])

    with pytest.raises(BusinessValidationError) as erreur:
        await _choisir(session, CLASSE_6A, maths.id, YAO)

    assert "Sophie Yao" in erreur.value.detail
    assert "Mathématiques" in erreur.value.detail
    assert "n'est pas retenu" in erreur.value.detail


@pytest.mark.asyncio
async def test_enregistrement_refuse_une_matiere_d_un_autre_niveau(session: AsyncSession) -> None:
    anglais_5e = await _matiere(session, "Anglais", NIVEAU_5E, [YAO])

    with pytest.raises(BusinessValidationError) as erreur:
        await _choisir(session, CLASSE_6A, anglais_5e.id, YAO)

    assert "Anglais" in erreur.value.detail
    assert "n'est pas enseignée dans cette classe" in erreur.value.detail


@pytest.mark.asyncio
async def test_enregistrement_sans_choix_retire_la_ligne(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])
    await _choisir(session, CLASSE_6A, maths.id, KOUASSI)

    await _choisir(session, CLASSE_6A, maths.id, None)

    entree = await _entree(session, CLASSE_6A, maths.id)
    assert (entree.source, entree.assigned_teacher_id) == ("none", None)


@pytest.mark.asyncio
async def test_enregistrement_journalise_les_choix(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])

    await _choisir(session, CLASSE_6A, maths.id, TRAORE)

    entrees = (
        (await session.execute(select(AuditLog).where(AuditLog.entity_type == "class")))
        .scalars()
        .all()
    )
    assert len(entrees) == 1
    assert entrees[0].new_values == {"subject_teachers": {str(maths.id): TRAORE}}


@pytest.mark.asyncio
async def test_classe_inconnue_refusee(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await svc.save_class_teachers(session, 9999, [], actor=ACTEUR)


@pytest.mark.asyncio
async def test_heures_hebdomadaires_suivent_l_enseignant_resolu_par_classe(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE], heures=4)
    await _matiere(session, "Anglais", NIVEAU_6E, [YAO], heures=3)
    await _matiere(session, "Histoire 5e", NIVEAU_5E, [KOUASSI], heures=9)
    await _choisir(session, CLASSE_6A, maths.id, KOUASSI)
    await _choisir(session, CLASSE_6B, maths.id, TRAORE)

    # Kouassi : maths en 6A (4) + histoire en 5A (9, unique enseignant du niveau)
    assert await workload.teacher_weekly_hours(session, KOUASSI) == 4 + 9
    assert await workload.teacher_weekly_hours(session, TRAORE) == 4
    # Yao : anglais dans les deux classes de 6e, unique enseignant du niveau
    assert await workload.teacher_weekly_hours(session, YAO) == 3 * 2


@pytest.mark.asyncio
async def test_heures_comptent_une_fois_par_classe_du_niveau(session: AsyncSession) -> None:
    await _matiere(session, "Sciences", NIVEAU_6E, [KOUASSI], heures=5)

    assert await workload.teacher_weekly_hours(session, KOUASSI) == 5 * 2


@pytest.mark.asyncio
async def test_serie_restreint_les_matieres_de_la_classe(session: AsyncSession) -> None:
    serie = Series(id=1, name="C", level_id=NIVEAU_6E)
    session.add(serie)
    await session.flush()
    scientifique = Subject(
        name="Physique C", level_id=NIVEAU_6E, series_id=serie.id, hours_per_week=6
    )
    session.add(scientifique)
    await session.flush()
    await subject_svc.set_subject_teachers(session, scientifique, [YAO])
    await session.commit()
    session.expunge_all()
    serie_classe = await session.get(Class, CLASSE_6A)
    assert serie_classe is not None
    serie_classe.series_id = serie.id
    await session.commit()
    session.expunge_all()

    entrees = await svc.resolve_class_teachers(session, await session.get(Class, CLASSE_6A))
    assert any(e.subject.name == "Physique C" for e in entrees)
    # Une classe sans série reçoit toutes les matières du niveau (règle inchangée, #527 à venir).
    autre = await session.get(Class, CLASSE_6B)
    assert autre is not None
    assert any(
        e.subject.name == "Physique C" for e in await svc.resolve_class_teachers(session, autre)
    )


CHEMIN_MIGRATION_0088 = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261028_0088_class_subject_teachers.py"
)


def _charger_migration_0088() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0088_class_subject_teachers", CHEMIN_MIGRATION_0088
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_recopie_des_index_rejouable_sans_index_sur_classe(session: AsyncSession) -> None:
    module = _charger_migration_0088()
    conn = await session.connection()
    await session.execute(text("DROP INDEX ix_class_subject_teachers_teacher_id"))

    await conn.run_sync(module._ensure_indexes)
    await conn.run_sync(module._ensure_indexes)

    noms = await conn.run_sync(
        lambda c: [ix["name"] for ix in inspect(c).get_indexes("class_subject_teachers")]
    )
    assert "ix_class_subject_teachers_teacher_id" in noms
    assert "ix_class_subject_teachers_subject_id" in noms
    assert not any(nom.endswith("class_id") for nom in noms)


@pytest.mark.asyncio
async def test_retrait_d_un_enseignant_purge_ses_choix_et_journalise_par_matiere(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])
    await _choisir(session, CLASSE_6A, maths.id, TRAORE)
    await _choisir(session, CLASSE_6B, maths.id, TRAORE)

    await subject_svc.unlink_teacher(session, TRAORE, actor=ACTEUR)
    await session.commit()

    restants = (await session.execute(select(ClassSubjectTeacher))).scalars().all()
    assert restants == []
    journal = (
        (await session.execute(select(AuditLog).where(AuditLog.entity_type == "subject")))
        .scalars()
        .all()
    )
    assert len(journal) == 1
    assert journal[0].entity_id == maths.id
    assert journal[0].old_values == {"class_teacher_choices_removed": [CLASSE_6A, CLASSE_6B]}
    assert journal[0].new_values == {"class_teacher_choices_removed": []}


@pytest.mark.asyncio
async def test_retrait_d_une_matiere_purge_le_choix_orphelin_et_journalise(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])
    await _choisir(session, CLASSE_6A, maths.id, TRAORE)
    attached = await session.get(Subject, maths.id)
    assert attached is not None

    await subject_svc.set_subject_teachers(session, attached, [KOUASSI], actor=ACTEUR)
    await session.commit()

    journal = (
        (await session.execute(select(AuditLog).where(AuditLog.entity_type == "subject")))
        .scalars()
        .all()
    )
    assert [j.old_values for j in journal] == [{"class_teacher_choices_removed": [CLASSE_6A]}]


@pytest.mark.asyncio
async def test_classe_sans_matiere_pour_son_niveau(session: AsyncSession) -> None:
    cinquieme = await session.get(Class, CLASSE_5A)
    assert cinquieme is not None

    assert await svc.resolve_class_teachers(session, cinquieme) == []
    cls, entrees = await svc.save_class_teachers(session, CLASSE_5A, [], actor=ACTEUR)
    assert cls.id == CLASSE_5A
    assert entrees == []


@pytest.mark.asyncio
async def test_sans_enseignant_resolu_aucun_nom_n_est_devine(session: AsyncSession) -> None:
    await _matiere(session, "Mathématiques", NIVEAU_6E, [KOUASSI, TRAORE])

    assert await svc.class_teacher_names(session, CLASSE_6A) == {}


def test_put_refuse_une_matiere_en_double() -> None:
    with pytest.raises(ValidationError):
        ClassSubjectTeachersUpdate(
            assignments=[
                {"subject_id": 1, "teacher_id": KOUASSI},
                {"subject_id": 1, "teacher_id": TRAORE},
            ]
        )


def test_put_refuse_plus_de_soixante_lignes() -> None:
    with pytest.raises(ValidationError):
        ClassSubjectTeachersUpdate(assignments=[{"subject_id": i} for i in range(1, 62)])
