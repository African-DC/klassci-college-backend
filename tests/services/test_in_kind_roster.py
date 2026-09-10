"""La liste de saisie en lot : une classe, ses élèves, ce qu'il reste à cocher.

Un éducateur repasse derrière soixante-dix-huit inscriptions pour dire qui est
nouveau et qui a déposé son paquet de rames. Fiche par fiche, en changeant
d'onglet à chaque fois, le travail ne se termine pas. Cette liste est ce qu'un
seul appel lui rend, classe par classe.

Ce que ces tests gardent, et c'est le même refus que partout ailleurs dans ce
domaine : **l'écran ne reçoit une case que pour un article que cet élève-là
peut réellement déposer**, et le profil remonte tel qu'il est, `None` compris.
Afficher une case sur un frais qui n'est pas au dossier serait inviter à cocher
une ligne qui n'existe pas ; pré-cocher un profil non tranché serait décider à
la place de l'éducateur.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, FeeCategory
from app.models.user import Student
from app.services import enrollment_fees

AY = 2026
CLASSE = 10
AUTRE_CLASSE = 11

CAT_RAMETTE = 100
CAT_CHEMISE = 101
CAT_SCOLARITE = 102

_TABLES = ("enrollments", "enrollment_fees", "fee_categories", "students")


def _sqlite_schema() -> list[Table]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    tables = []
    for nom in _TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


class _AsyncBridge:
    """Le pont synchrone/asynchrone des autres tests de ce dossier."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                FeeCategory(
                    id=CAT_RAMETTE, name="Ramette", is_mandatory=True, accepts_in_kind=True
                ),
                FeeCategory(
                    id=CAT_CHEMISE, name="Chemise", is_mandatory=True, accepts_in_kind=True
                ),
                FeeCategory(
                    id=CAT_SCOLARITE, name="Scolarite", is_mandatory=True, accepts_in_kind=False
                ),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _eleve(db: _AsyncBridge, student_id: int, nom: str, prenom: str = "A") -> None:
    db.add(Student(id=student_id, first_name=prenom, last_name=nom))
    db._session.flush()


def _inscrire(
    db: _AsyncBridge,
    enrollment_id: int,
    student_id: int,
    *,
    classe: int = CLASSE,
    profil: bool | None = None,
    statut: EnrollmentStatus = EnrollmentStatus.VALIDE,
) -> None:
    db.add(
        Enrollment(
            id=enrollment_id,
            student_id=student_id,
            class_id=classe,
            academic_year_id=AY,
            status=statut,
            is_new_student=profil,
        )
    )
    db._session.flush()


def _facturer(
    db: _AsyncBridge,
    fee_id: int,
    enrollment_id: int,
    category_id: int,
    *,
    statut: EnrollmentFeeStatus = EnrollmentFeeStatus.PENDING,
) -> None:
    db.add(
        EnrollmentFee(
            id=fee_id,
            enrollment_id=enrollment_id,
            fee_variant_id=fee_id,
            fee_category_id=category_id,
            amount=2500,
            status=statut,
        )
    )
    db._session.flush()


async def _liste(db: _AsyncBridge, classe: int = CLASSE) -> list:
    return await enrollment_fees.in_kind_roster(
        db,  # type: ignore[arg-type]
        class_id=classe,
        academic_year_id=AY,
    )


async def test_la_liste_ne_porte_que_les_articles_deposables(db: _AsyncBridge) -> None:
    """La scolarité n'est pas un article : aucune case ne doit l'annoncer."""
    _eleve(db, 1, "Kouadio")
    _inscrire(db, 500, 1)
    _facturer(db, 300, 500, CAT_RAMETTE)
    _facturer(db, 301, 500, CAT_SCOLARITE)

    lignes = await _liste(db)

    assert len(lignes) == 1
    assert [a.category_name for a in lignes[0].fees] == ["Ramette"]


async def test_une_case_n_existe_que_si_le_frais_est_au_dossier(db: _AsyncBridge) -> None:
    """Deux élèves de la même classe, deux dossiers différents.

    Celui qui ne doit pas la chemise ne doit pas voir sa case : elle
    n'inviterait qu'à cocher une ligne qui n'existe pas.
    """
    _eleve(db, 1, "Adjoua")
    _eleve(db, 2, "Bamba")
    _inscrire(db, 500, 1)
    _inscrire(db, 501, 2)
    _facturer(db, 300, 500, CAT_RAMETTE)
    _facturer(db, 301, 500, CAT_CHEMISE)
    _facturer(db, 302, 501, CAT_RAMETTE)

    lignes = await _liste(db)

    par_nom = {ligne.last_name: ligne for ligne in lignes}
    assert [a.category_name for a in par_nom["Adjoua"].fees] == ["Chemise", "Ramette"]
    assert [a.category_name for a in par_nom["Bamba"].fees] == ["Ramette"]


async def test_le_profil_non_tranche_remonte_tel_quel(db: _AsyncBridge) -> None:
    """L'écran n'a rien à pré-cocher : `None` n'est pas `False`."""
    _eleve(db, 1, "Kone")
    _eleve(db, 2, "Traore")
    _eleve(db, 3, "Yao")
    _inscrire(db, 500, 1, profil=None)
    _inscrire(db, 501, 2, profil=True)
    _inscrire(db, 502, 3, profil=False)

    profils = {ligne.last_name: ligne.is_new_student for ligne in await _liste(db)}

    assert profils == {"Kone": None, "Traore": True, "Yao": False}


async def test_un_depot_deja_pose_se_voit_dans_la_liste(db: _AsyncBridge) -> None:
    """L'éducateur doit distinguer ce qu'il reste à faire de ce qui est fait,
    sinon il recoche ce qui l'est déjà."""
    _eleve(db, 1, "Kouassi")
    _inscrire(db, 500, 1)
    _facturer(db, 300, 500, CAT_RAMETTE, statut=EnrollmentFeeStatus.IN_KIND)

    lignes = await _liste(db)

    assert lignes[0].fees[0].status == EnrollmentFeeStatus.IN_KIND


async def test_une_autre_classe_n_apparait_pas(db: _AsyncBridge) -> None:
    """Une classe à la fois : c'est l'unité de travail de l'éducateur."""
    _eleve(db, 1, "Ici")
    _eleve(db, 2, "Ailleurs")
    _inscrire(db, 500, 1, classe=CLASSE)
    _inscrire(db, 501, 2, classe=AUTRE_CLASSE)

    lignes = await _liste(db)

    assert [ligne.last_name for ligne in lignes] == ["Ici"]


async def test_un_dossier_annule_n_est_pas_a_renseigner(db: _AsyncBridge) -> None:
    """Faire perdre du temps sur un élève qui n'est pas là est la meilleure
    façon que le travail ne soit pas terminé."""
    _eleve(db, 1, "Present")
    _eleve(db, 2, "Annule")
    _inscrire(db, 500, 1)
    _inscrire(db, 501, 2, statut=EnrollmentStatus.ANNULE)

    lignes = await _liste(db)

    assert [ligne.last_name for ligne in lignes] == ["Present"]


async def test_la_liste_est_triee_sur_le_nom(db: _AsyncBridge) -> None:
    """L'éducateur a sa liste de classe sous les yeux, dans cet ordre-là."""
    _eleve(db, 1, "Zongo")
    _eleve(db, 2, "Ackah")
    _inscrire(db, 500, 1)
    _inscrire(db, 501, 2)

    assert [ligne.last_name for ligne in await _liste(db)] == ["Ackah", "Zongo"]
