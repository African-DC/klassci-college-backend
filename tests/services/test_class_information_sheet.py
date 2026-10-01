"""La fiche de renseignements : forme, tri, et qui n'y figure pas."""

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.deep_report import Scholarship
from app.models.enrollment import EnrollmentStatus
from app.services import class_information_sheet
from tests.services._sheet_world import (
    AN_COURANT,
    AN_PASSE,
    CLASSE_3E,
    CLASSE_4E,
    CLASSE_5E,
    CLASSE_6E,
    AsyncBridge,
    add_enrollment,
    add_student,
    build_school,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    for session in build_school():
        add_student(
            session,
            1,
            "Zadi",
            "Ange",
            genre="M",
            enrollment_number="M-001",
            birth_date=date(2013, 4, 2),
            birth_place="Daloa",
            nationality="Ivoirienne",
            photo_url="/uploads/zadi.jpg",
        )
        add_student(session, 2, "Bamba", "Fatou", genre="F")
        add_student(session, 3, "Bamba", "Awa")
        add_student(session, 4, "Annulé", "Paul")
        add_student(session, 5, "Archivé", "Marc")
        add_student(session, 6, "Coulibaly", "Seydou")
        add_enrollment(
            session,
            1,
            1,
            CLASSE_4E,
            AN_COURANT,
            assignment_status="affecte",
            is_repeater=True,
            lv2="espagnol",
            artistic_discipline="musique",
            previous_level="4E",
        )
        add_enrollment(session, 2, 2, CLASSE_4E, AN_COURANT, status=EnrollmentStatus.EN_VALIDATION)
        add_enrollment(session, 3, 3, CLASSE_4E, AN_COURANT)
        add_enrollment(session, 4, 4, CLASSE_4E, AN_COURANT, status=EnrollmentStatus.ANNULE)
        add_enrollment(session, 5, 5, CLASSE_4E, AN_COURANT, archived_at=datetime(2026, 9, 9))
        add_enrollment(session, 6, 6, CLASSE_6E, AN_COURANT)
        add_enrollment(session, 7, 6, CLASSE_3E, AN_PASSE)
        session.add(Scholarship(enrollment_id=1, kind="demi_bourse"))
        session.commit()
        yield session


@pytest.mark.asyncio
async def test_une_classe_triee_par_nom_puis_prenom_sans_annule_ni_corbeille(db: Session) -> None:
    fiche = await class_information_sheet.class_sheet(
        AsyncBridge(db),  # type: ignore[arg-type]
        CLASSE_4E,
    )

    assert fiche.academic_year.model_dump() == {"id": AN_COURANT, "name": "2026-2027"}
    assert len(fiche.classes) == 1
    classe = fiche.classes[0]
    assert (classe.id, classe.name, classe.level_name) == (CLASSE_4E, "4ème 1", "4eme")
    assert [r.enrollment_id for r in classe.rows] == [3, 2, 1]


@pytest.mark.asyncio
async def test_une_ligne_porte_les_seize_colonnes(db: Session) -> None:
    fiche = await class_information_sheet.class_sheet(
        AsyncBridge(db),  # type: ignore[arg-type]
        CLASSE_4E,
        AN_COURANT,
    )

    ligne = fiche.classes[0].rows[-1].model_dump(mode="json")
    assert ligne == {
        "enrollment_id": 1,
        "matricule": "M-001",
        "last_name": "Zadi",
        "first_name": "Ange",
        "genre": "M",
        "level_name": "4eme",
        "birth_date": "2013-04-02",
        "birth_place": "Daloa",
        "nationality": "Ivoirienne",
        "assignment_status": "affecte",
        "scholarship_kind": "demi_bourse",
        "is_repeater": True,
        "lv2": "espagnol",
        "artistic_discipline": "musique",
        "has_photo": True,
        "previous_level": "4E",
        "previous_series": None,
    }
    vide = fiche.classes[0].rows[0]
    assert vide.has_photo is False
    assert vide.scholarship_kind is None
    assert vide.genre is None


@pytest.mark.asyncio
async def test_une_classe_sans_inscrit_rend_une_fiche_vide(db: Session) -> None:
    fiche = await class_information_sheet.class_sheet(
        AsyncBridge(db),  # type: ignore[arg-type]
        CLASSE_5E,
    )

    assert fiche.classes[0].rows == []
    assert fiche.classes[0].level_name == "Cinquième"


@pytest.mark.asyncio
async def test_une_classe_inconnue_rend_404(db: Session) -> None:
    with pytest.raises(NotFoundError):
        await class_information_sheet.class_sheet(AsyncBridge(db), 999)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_toute_l_ecole_classes_par_niveau_en_nombre_fixe_de_requetes(db: Session) -> None:
    requetes: list[str] = []
    moteur = db.get_bind()
    event.listen(moteur, "before_cursor_execute", lambda *a: requetes.append(a[2]))

    fiche = await class_information_sheet.school_sheet(AsyncBridge(db))  # type: ignore[arg-type]

    assert [c.id for c in fiche.classes] == [CLASSE_6E, CLASSE_4E]
    assert [len(c.rows) for c in fiche.classes] == [1, 3]
    # Année, inscriptions, puis une requête par relation chargée : élève,
    # classe, niveau, bourse. Le nombre ne dépend pas du nombre d'élèves.
    assert len(requetes) == 6


@pytest.mark.asyncio
async def test_l_annee_passee_se_demande_explicitement(db: Session) -> None:
    fiche = await class_information_sheet.school_sheet(
        AsyncBridge(db),  # type: ignore[arg-type]
        AN_PASSE,
    )

    assert fiche.academic_year.name == "2025-2026"
    assert [c.id for c in fiche.classes] == [CLASSE_3E]
