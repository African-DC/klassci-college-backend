"""Disponibilités enseignant — sur une vraie base, avec de vraies requêtes.

Deux gestes que la fonctionnalité existe pour permettre, et qu'aucun test ne
couvrait tant que rien ne les exposait :

- le secrétariat consulte la semaine d'un enseignant avant de lui poser un
  créneau, et doit y voir *à la fois* ses cours dans les autres classes et les
  plages qu'il a fermées, dans l'ordre de la semaine ;
- l'enseignant ne touche qu'à ses propres plages, y compris quand il devine
  l'identifiant de celle d'un collègue.

Les tests tournent sur SQLite via le module standard : ils exécutent le vrai
SQL du service, sans pilote asynchrone supplémentaire ni MySQL à provisionner.
"""

from collections.abc import Iterator
from datetime import time

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class, Subject
from app.models.timetable import DayOfWeek, TeacherAvailability, TimetableSlot
from app.models.user import TeacherProfile
from app.schemas.timetable import TeacherAvailabilityCreate, TeacherAvailabilityUpdate
from app.services import teacher_availability_service as svc

ANNEE = 2026
AISSATOU = 1
KOUASSI = 2
SIXIEME_B = 10
FRANCAIS = 20


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session SQLAlchemy synchrone.

    Le service n'utilise que ces gestes ; les envelopper évite d'ajouter un
    pilote asynchrone à la seule fin de faire tourner des tests.
    """

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

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)


def _sqlite_schema() -> list[Table]:
    """Les tables utiles, transposées pour SQLite.

    SQLite ne numérote automatiquement que les colonnes « INTEGER PRIMARY
    KEY » : les `BIGINT` du modèle refuseraient un INSERT sans identifiant. On
    travaille sur une copie du schéma, jamais sur les tables du modèle que les
    autres tests lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in (
        "classes",
        "subjects",
        "rooms",
        "teacher_profiles",
        "timetable_slots",
        "teacher_availabilities",
    ):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


def _cours(slot_id: int, jour: DayOfWeek, debut: str, fin: str) -> TimetableSlot:
    h1, m1 = debut.split(":")
    h2, m2 = fin.split(":")
    return TimetableSlot(
        id=slot_id,
        class_id=SIXIEME_B,
        teacher_id=AISSATOU,
        subject_id=FRANCAIS,
        academic_year_id=ANNEE,
        day=jour.value,
        start_time=time(int(h1), int(m1)),
        end_time=time(int(h2), int(m2)),
    )


def _plage_fermee(av_id: int, teacher_id: int, jour: DayOfWeek, debut: time, fin: time):
    return TeacherAvailability(
        id=av_id,
        teacher_id=teacher_id,
        day=jour.value,
        start_time=debut,
        end_time=fin,
        available=False,
    )


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve par test : deux enseignants, une classe, une matière."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Class(id=SIXIEME_B, name="6eme B", level_id=1, series_id=None),
                Subject(id=FRANCAIS, name="Francais", coefficient=4),
                TeacherProfile(id=AISSATOU, user_id=101, first_name="Aissatou", last_name="Diallo"),
                TeacherProfile(id=KOUASSI, user_id=102, first_name="Jean", last_name="Kouassi"),
            ]
        )
        session.commit()
        yield _AsyncBridge(session)


@pytest.mark.asyncio
async def test_semaine_melange_cours_et_plages_fermees(db: _AsyncBridge) -> None:
    """La semaine consultée montre l'empêchement, quelle qu'en soit la nature."""
    db.add(_cours(1, DayOfWeek.TUESDAY, "08:00", "10:00"))
    db.add(_plage_fermee(1, AISSATOU, DayOfWeek.MONDAY, time(15, 0), time(17, 0)))
    await db.commit()

    semaine = await svc.week_for_teacher(db, AISSATOU, academic_year_id=ANNEE)  # type: ignore[arg-type]

    assert semaine.teacher_name == "Aissatou Diallo"
    assert [(b.day, b.start_time, b.kind) for b in semaine.busy] == [
        ("monday", "15:00", "unavailable"),
        ("tuesday", "08:00", "course"),
    ]
    cours = semaine.busy[1]
    assert cours.label == "Francais"
    assert cours.class_name == "6eme B"


@pytest.mark.asyncio
async def test_plage_ouverte_annoncee_a_part(db: _AsyncBridge) -> None:
    """Une plage ouverte n'empêche rien, mais dit que le reste est fermé.

    Sans `has_declarations`, l'écran verrait une semaine vide d'empêchements là
    où la création sera refusée partout sauf le lundi matin.
    """
    db.add(
        TeacherAvailability(
            id=1,
            teacher_id=AISSATOU,
            day=DayOfWeek.MONDAY.value,
            start_time=time(8, 0),
            end_time=time(12, 0),
            available=True,
            preferred=True,
        )
    )
    await db.commit()

    semaine = await svc.week_for_teacher(db, AISSATOU, academic_year_id=ANNEE)  # type: ignore[arg-type]

    assert semaine.busy == []
    assert semaine.has_declarations is True
    assert [(o.day, o.start_time, o.end_time, o.preferred) for o in semaine.open] == [
        ("monday", "08:00", "12:00", True)
    ]


@pytest.mark.asyncio
async def test_sans_declaration_la_semaine_ne_contraint_rien(db: _AsyncBridge) -> None:
    """Rien de déclaré : aucune contrainte, et l'écran doit pouvoir le dire."""
    semaine = await svc.week_for_teacher(db, AISSATOU, academic_year_id=ANNEE)  # type: ignore[arg-type]

    assert semaine.has_declarations is False
    assert semaine.open == []
    assert semaine.busy == []


@pytest.mark.asyncio
async def test_semaine_d_un_enseignant_inconnu(db: _AsyncBridge) -> None:
    """Consulter la semaine de personne se dit, plutôt que de renvoyer du vide."""
    with pytest.raises(NotFoundError):
        await svc.week_for_teacher(db, 999, academic_year_id=ANNEE)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_declaration_puis_relecture(db: _AsyncBridge) -> None:
    """Ce qui est déclaré se relit tel quel, et ferme bien la plage."""
    cree = await svc.create(  # type: ignore[arg-type]
        db,
        AISSATOU,
        TeacherAvailabilityCreate(
            day=DayOfWeek.WEDNESDAY, start_time="14:00", end_time="18:00", available=False
        ),
    )

    assert (cree.day, cree.start_time, cree.end_time, cree.available) == (
        "wednesday",
        "14:00",
        "18:00",
        False,
    )
    assert [a.id for a in await svc.list_for_teacher(db, AISSATOU)] == [cree.id]  # type: ignore[arg-type]

    semaine = await svc.week_for_teacher(db, AISSATOU, academic_year_id=ANNEE)  # type: ignore[arg-type]
    assert [(b.day, b.kind) for b in semaine.busy] == [("wednesday", "unavailable")]


@pytest.mark.asyncio
async def test_heure_de_fin_avant_le_debut_refusee(db: _AsyncBridge) -> None:
    """Une plage à l'envers est refusée avec la raison, pas avec un 500."""
    with pytest.raises(BusinessValidationError) as erreur:
        await svc.create(  # type: ignore[arg-type]
            db,
            AISSATOU,
            TeacherAvailabilityCreate(
                day=DayOfWeek.WEDNESDAY, start_time="18:00", end_time="14:00"
            ),
        )

    assert "après l'heure de début" in erreur.value.detail


@pytest.mark.asyncio
async def test_heure_mal_formee_refusee(db: _AsyncBridge) -> None:
    """« 14h » n'est pas une heure : on le dit au lieu de planter au parse."""
    with pytest.raises(BusinessValidationError) as erreur:
        await svc.create(  # type: ignore[arg-type]
            db,
            AISSATOU,
            TeacherAvailabilityCreate(day=DayOfWeek.WEDNESDAY, start_time="14h", end_time="18:00"),
        )

    assert "HH:MM" in erreur.value.detail


@pytest.mark.asyncio
async def test_un_enseignant_ne_touche_pas_la_plage_d_un_collegue(db: _AsyncBridge) -> None:
    """Deviner l'identifiant d'un collègue ne donne aucun pouvoir dessus."""
    plage = await svc.create(  # type: ignore[arg-type]
        db,
        KOUASSI,
        TeacherAvailabilityCreate(
            day=DayOfWeek.MONDAY, start_time="08:00", end_time="10:00", available=False
        ),
    )

    with pytest.raises(NotFoundError):
        await svc.remove(db, plage.id, teacher_id=AISSATOU)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.update(  # type: ignore[arg-type]
            db, plage.id, TeacherAvailabilityUpdate(available=True), teacher_id=AISSATOU
        )

    assert [a.id for a in await svc.list_for_teacher(db, KOUASSI)] == [plage.id]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_l_administration_modifie_la_plage_de_n_importe_qui(db: _AsyncBridge) -> None:
    """Sans identifiant enseignant, c'est l'administration : elle passe partout.

    C'est le cas ROSTAN : l'enseignant a prévenu de vive voix, le directeur des
    études saisit à sa place.
    """
    plage = await svc.create(  # type: ignore[arg-type]
        db,
        KOUASSI,
        TeacherAvailabilityCreate(
            day=DayOfWeek.MONDAY, start_time="08:00", end_time="10:00", available=False
        ),
    )

    rouverte = await svc.update(db, plage.id, TeacherAvailabilityUpdate(available=True))  # type: ignore[arg-type]
    assert rouverte.available is True

    await svc.remove(db, plage.id)  # type: ignore[arg-type]
    assert await svc.list_for_teacher(db, KOUASSI) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_supprimer_une_plage_inexistante(db: _AsyncBridge) -> None:
    """Supprimer ce qui n'existe pas est un 404, pas un succès silencieux."""
    with pytest.raises(NotFoundError):
        await svc.remove(db, 4242)  # type: ignore[arg-type]
