"""Plusieurs enseignants par matière : création, modification, copie et comptes.

Ces tests exécutent les vrais services sur une base SQLite en mémoire, avec une
vraie session asynchrone : ils lisent ce qui est réellement enregistré, ordre
compris. Une session synchrone ne suffit pas, les services utilisent
`begin_nested()`.
"""

import importlib.util
from collections.abc import AsyncIterator
from datetime import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import Integer, MetaData, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Level, Subject
from app.models.audit import AuditLog
from app.models.subject_teacher import SubjectTeacher
from app.models.timetable import DayOfWeek, TimetableSlot
from app.models.user import TeacherProfile
from app.repositories import subject_teacher_repository as srepo
from app.schemas.admin import SubjectCreate, SubjectDuplicateRequest, SubjectResponse, SubjectUpdate
from app.services import admin_service
from app.services import subject_teachers as svc

NIVEAU_6E = 1
NIVEAU_5E = 2
KOUASSI, TRAORE, YAO = 1, 2, 3
ACTEUR = 1
TABLES = (
    "levels",
    "series",
    "subjects",
    "teacher_profiles",
    "subject_teachers",
    "timetable_slots",
    "audit_logs",
)
CHEMIN_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261028_0087_subject_teachers.py"
)


def _schema() -> list[Any]:
    """Les tables utiles, transposées pour SQLite (identifiants auto-numérotés)."""
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
    """Deux niveaux, trois enseignants, aucune matière."""
    moteur = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = _schema()
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: MetaData().create_all(c, tables=tables))

    async with AsyncSession(moteur, expire_on_commit=False) as db:
        db.add_all(
            [
                Level(id=NIVEAU_6E, name="6e", order=1),
                Level(id=NIVEAU_5E, name="5e", order=2),
                TeacherProfile(id=KOUASSI, user_id=101, first_name="Jean", last_name="Kouassi"),
                TeacherProfile(id=TRAORE, user_id=102, first_name="Awa", last_name="Traoré"),
                TeacherProfile(id=YAO, user_id=103, first_name="Sophie", last_name="Yao"),
            ]
        )
        await db.commit()
        yield db
    await moteur.dispose()


async def _matiere(db: AsyncSession, nom: str, **kwargs: Any) -> SubjectResponse:
    data = SubjectCreate(name=nom, level_id=NIVEAU_6E, **kwargs)
    return await admin_service.create_subject(db, data, created_by=ACTEUR)


def _noms(reponse: SubjectResponse) -> list[str]:
    return [t.full_name for t in reponse.teachers]


@pytest.mark.asyncio
async def test_creation_avec_deux_enseignants_garde_l_ordre(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[TRAORE, KOUASSI])

    assert _noms(cree) == ["Awa Traoré", "Jean Kouassi"]
    assert cree.teacher_id == TRAORE
    assert cree.teacher_name == "Awa Traoré"


@pytest.mark.asyncio
async def test_teacher_id_seul_reste_accepte(session: AsyncSession) -> None:
    cree = await _matiere(session, "Anglais", teacher_id=YAO)

    assert _noms(cree) == ["Sophie Yao"]
    assert cree.teacher_id == YAO


@pytest.mark.asyncio
async def test_doublons_retires_en_gardant_le_premier_rang(session: AsyncSession) -> None:
    cree = await _matiere(session, "Physique", teacher_ids=[YAO, KOUASSI, YAO])

    assert _noms(cree) == ["Sophie Yao", "Jean Kouassi"]


@pytest.mark.asyncio
async def test_enseignant_inconnu_refuse_et_nomme_l_identifiant(session: AsyncSession) -> None:
    with pytest.raises(BusinessValidationError) as erreur:
        await _matiere(session, "SVT", teacher_ids=[KOUASSI, 999])

    assert "999" in erreur.value.detail
    assert "introuvable" in erreur.value.detail


@pytest.mark.asyncio
async def test_plus_de_trente_enseignants_refuses(session: AsyncSession) -> None:
    matiere = Subject(name="Histoire", level_id=NIVEAU_6E)
    session.add(matiere)
    await session.flush()

    with pytest.raises(BusinessValidationError):
        await svc.validate_teacher_ids(session, list(range(1, 32)))


@pytest.mark.asyncio
async def test_modification_reordonne_sans_conflit_d_unicite(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])

    modifie = await admin_service.update_subject(
        session,
        cree.id,
        SubjectUpdate(teacher_ids=[TRAORE, KOUASSI]),
        updated_by=ACTEUR,
    )

    assert _noms(modifie) == ["Awa Traoré", "Jean Kouassi"]
    assert modifie.teacher_id == TRAORE


@pytest.mark.asyncio
async def test_modification_sans_teacher_ids_garde_les_enseignants(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])

    renomme = await admin_service.update_subject(
        session,
        cree.id,
        SubjectUpdate(name="Maths"),
        updated_by=ACTEUR,
    )

    assert renomme.name == "Maths"
    assert _noms(renomme) == ["Jean Kouassi", "Awa Traoré"]


@pytest.mark.asyncio
async def test_liste_vide_retire_tous_les_enseignants(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])

    vide = await admin_service.update_subject(
        session,
        cree.id,
        SubjectUpdate(teacher_ids=[]),
        updated_by=ACTEUR,
    )

    assert vide.teachers == []
    assert vide.teacher_id is None
    assert vide.teacher_name is None


@pytest.mark.asyncio
async def test_teacher_id_legacy_en_modification_remplace_la_liste(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])

    modifie = await admin_service.update_subject(
        session,
        cree.id,
        SubjectUpdate(teacher_id=YAO),
        updated_by=ACTEUR,
    )

    assert _noms(modifie) == ["Sophie Yao"]


@pytest.mark.asyncio
async def test_changement_d_enseignants_est_journalise(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])

    await admin_service.update_subject(
        session,
        cree.id,
        SubjectUpdate(teacher_ids=[KOUASSI, YAO]),
        updated_by=ACTEUR,
    )

    entrees = (await session.execute(select(AuditLog))).scalars().all()
    avant_apres = [(e.old_values, e.new_values) for e in entrees]
    assert ({"teacher_ids": [KOUASSI]}, {"teacher_ids": [KOUASSI, YAO]}) in avant_apres


@pytest.mark.asyncio
async def test_copie_reprend_les_enseignants_demandes(session: AsyncSession) -> None:
    source = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])

    copie = await admin_service.duplicate_subject(
        session,
        SubjectDuplicateRequest(
            subject_id=source.id,
            level_id=NIVEAU_5E,
            teacher_ids=[YAO, TRAORE],
        ),
        created_by=ACTEUR,
    )

    assert copie.level_id == NIVEAU_5E
    assert _noms(copie) == ["Sophie Yao", "Awa Traoré"]


@pytest.mark.asyncio
async def test_copie_sans_enseignant_demande_reste_sans_enseignant(session: AsyncSession) -> None:
    source = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])

    copie = await admin_service.duplicate_subject(
        session,
        SubjectDuplicateRequest(subject_id=source.id, level_id=NIVEAU_5E),
        created_by=ACTEUR,
    )

    assert copie.teachers == []
    assert copie.teacher_id is None


async def _creneau(db: AsyncSession, matiere: int, enseignant: int, heure: int) -> None:
    db.add(
        TimetableSlot(
            class_id=1,
            teacher_id=enseignant,
            subject_id=matiere,
            academic_year_id=1,
            day=DayOfWeek.MONDAY.value,
            start_time=time(heure, 0),
            end_time=time(heure + 1, 0),
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_comptage_des_creneaux_par_enseignant(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])
    await _creneau(session, cree.id, KOUASSI, 8)
    await _creneau(session, cree.id, KOUASSI, 9)
    await _creneau(session, cree.id, TRAORE, 10)

    comptes = await srepo.count_slots_by_teacher(session, cree.id)

    assert [(c.teacher_id, c.slots) for c in comptes] == [(KOUASSI, 2), (TRAORE, 1)]


@pytest.mark.asyncio
async def test_route_des_creneaux_renvoie_une_liste_triee(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])
    await _creneau(session, cree.id, TRAORE, 8)

    reponse = await svc.slot_counts_for_subject(session, cree.id)

    assert [(c.teacher_id, c.slots) for c in reponse.counts] == [(TRAORE, 1)]


@pytest.mark.asyncio
async def test_route_des_creneaux_matiere_inconnue(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await svc.slot_counts_for_subject(session, 4242)


@pytest.mark.asyncio
async def test_tableau_de_bord_compte_les_instances_sans_enseignant(session: AsyncSession) -> None:
    await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])
    await _matiere(session, "Anglais")
    session.add(Subject(name="Catalogue sans niveau", level_id=None))
    await session.commit()

    assert await srepo.count_instances_without_teacher(session) == 1


def _charger_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0087_subject_teachers", CHEMIN_MIGRATION
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_recopie_de_migration_un_rang_par_matiere_et_rejouable(session: AsyncSession) -> None:
    session.add_all(
        [
            Subject(id=1, name="Mathématiques", level_id=NIVEAU_6E, teacher_id=KOUASSI),
            Subject(id=2, name="Anglais", level_id=NIVEAU_6E, teacher_id=None),
            Subject(id=3, name="Physique", level_id=NIVEAU_5E, teacher_id=YAO),
        ]
    )
    await session.commit()
    sql = _charger_migration().COPY_SQL

    await session.execute(text(sql))
    await session.execute(text(sql))
    await session.commit()

    lignes = (
        await session.execute(
            select(SubjectTeacher.subject_id, SubjectTeacher.teacher_id, SubjectTeacher.position)
        )
    ).all()
    assert sorted(lignes) == [(1, KOUASSI, 0), (3, YAO, 0)]


@pytest.mark.asyncio
async def test_modification_avec_enseignant_inconnu_ne_change_rien(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])

    with pytest.raises(BusinessValidationError):
        await admin_service.update_subject(
            session,
            cree.id,
            SubjectUpdate(name="Maths", teacher_ids=[TRAORE, 999]),
            updated_by=ACTEUR,
        )

    relu = await admin_service.get_subject(session, cree.id)
    assert relu.name == "Mathématiques"
    assert _noms(relu) == ["Jean Kouassi"]


@pytest.mark.asyncio
async def test_copie_avec_enseignant_inconnu_ne_cree_rien(session: AsyncSession) -> None:
    source = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI])

    with pytest.raises(BusinessValidationError):
        await admin_service.duplicate_subject(
            session,
            SubjectDuplicateRequest(subject_id=source.id, level_id=NIVEAU_5E, teacher_ids=[999]),
            created_by=ACTEUR,
        )

    total = await session.scalar(
        select(func.count(Subject.id)).where(Subject.level_id == NIVEAU_5E)
    )
    assert total == 0


@pytest.mark.asyncio
async def test_suppression_du_premier_enseignant_promeut_le_suivant(session: AsyncSession) -> None:
    cree = await _matiere(session, "Mathématiques", teacher_ids=[KOUASSI, TRAORE])
    enseignant = await session.get(TeacherProfile, KOUASSI)
    assert enseignant is not None

    await admin_service.TEACHER_KIND.delete(session, enseignant)
    await session.commit()

    relu = await admin_service.get_subject(session, cree.id)
    assert relu.teacher_id == TRAORE
    assert _noms(relu) == ["Awa Traoré"]


@pytest.mark.asyncio
async def test_recopie_des_index_rejouable_sur_sqlite(session: AsyncSession) -> None:
    module = _charger_migration()
    conn = await session.connection()
    await session.execute(text("DROP INDEX ix_subject_teachers_teacher_id"))

    await conn.run_sync(module._ensure_indexes)
    await conn.run_sync(module._ensure_indexes)

    noms = await conn.run_sync(
        lambda c: [ix["name"] for ix in inspect(c).get_indexes("subject_teachers")]
    )
    assert noms.count("ix_subject_teachers_teacher_id") == 1
