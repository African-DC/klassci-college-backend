"""Telechargement d'un bulletin depuis un portail : qui passe, qui est refuse.

Les fonctions de service sont appelees pour de vrai, sur le decor partage
`tests.bulletin_portal_decor`.
"""

import pytest
from fastapi import HTTPException

from app.core.exceptions import NotFoundError
from app.services import bulletin_access
from app.services import parent_portal_service as parent_service
from app.services import student_portal_service as student_service
from tests.bulletin_portal_decor import (
    CLASSMATE_ID,
    CLASSMATE_PUBLISHED,
    FAKE_PDF,
    OWN_DRAFT,
    OWN_PUBLISHED,
    STUDENT_ID,
    UNKNOWN_BULLETIN,
    BulletinsDb,
    close_payment_gate,
    install_pdf_factory,
    login_parent,
    login_student,
    login_student_without_record,
    open_payment_gate,
)

STUDENT_USER_ID = 3
PARENT_USER_ID = 10


@pytest.fixture
def db() -> BulletinsDb:
    return BulletinsDb()


@pytest.fixture(autouse=True)
def pdf_factory(monkeypatch) -> None:
    install_pdf_factory(monkeypatch)


@pytest.fixture
def released(monkeypatch) -> list[int]:
    return open_payment_gate(monkeypatch)


@pytest.fixture
def blocked(monkeypatch) -> None:
    close_payment_gate(monkeypatch)


@pytest.fixture
def as_student(monkeypatch) -> None:
    login_student(monkeypatch)


@pytest.fixture
def as_parent(monkeypatch) -> None:
    login_parent(monkeypatch)


# ---------------------------------------------------------------------------
# L'eleve
# ---------------------------------------------------------------------------


async def test_eleve_telecharge_son_bulletin_publie(db, as_student, released) -> None:
    """Le cas nominal : son bulletin, publie, sans impaye — le PDF sort."""
    pdf = await student_service.get_bulletin_pdf(
        db, user_id=STUDENT_USER_ID, bulletin_id=OWN_PUBLISHED
    )
    assert pdf == FAKE_PDF


async def test_eleve_refuse_le_bulletin_d_un_camarade(db, as_student, released) -> None:
    """Le bulletin d'un camarade est introuvable, pas « interdit »."""
    with pytest.raises(NotFoundError) as exc:
        await student_service.get_bulletin_pdf(
            db, user_id=STUDENT_USER_ID, bulletin_id=CLASSMATE_PUBLISHED
        )
    assert exc.value.status_code == 404


async def test_eleve_refuse_son_bulletin_non_publie(db, as_student, released) -> None:
    """Deviner l'identifiant d'un bulletin non publie ne doit rien donner."""
    with pytest.raises(NotFoundError) as exc:
        await student_service.get_bulletin_pdf(db, user_id=STUDENT_USER_ID, bulletin_id=OWN_DRAFT)
    assert exc.value.status_code == 404


async def test_eleve_refuse_un_bulletin_inexistant(db, as_student, released) -> None:
    """Un identifiant qui ne correspond a rien rend le meme refus."""
    with pytest.raises(NotFoundError):
        await student_service.get_bulletin_pdf(
            db, user_id=STUDENT_USER_ID, bulletin_id=UNKNOWN_BULLETIN
        )


async def test_eleve_sans_fiche_eleve(db, monkeypatch, released) -> None:
    """Un compte qui ne pointe sur aucune fiche eleve n'obtient rien."""
    login_student_without_record(monkeypatch)
    with pytest.raises(NotFoundError):
        await student_service.get_bulletin_pdf(
            db, user_id=STUDENT_USER_ID, bulletin_id=OWN_PUBLISHED
        )


async def test_eleve_retenu_pour_impaye(db, as_student, blocked) -> None:
    """La famille en retard est retenue en 402, et ne peut pas y deroger seule."""
    with pytest.raises(HTTPException) as exc:
        await student_service.get_bulletin_pdf(
            db, user_id=STUDENT_USER_ID, bulletin_id=OWN_PUBLISHED
        )
    assert exc.value.status_code == 402
    assert exc.value.detail["can_override"] is False


async def test_l_appartenance_passe_avant_la_porte_de_paiement(db, as_student, released) -> None:
    """Sur le bulletin d'un camarade, la porte de paiement n'est jamais interrogee.

    Elle repond 402 en annoncant le montant impaye et l'identifiant de l'eleve :
    l'atteindre revelerait l'existence du bulletin et la situation financiere
    de la famille visee.
    """
    with pytest.raises(NotFoundError):
        await student_service.get_bulletin_pdf(
            db, user_id=STUDENT_USER_ID, bulletin_id=CLASSMATE_PUBLISHED
        )
    assert released == []


# ---------------------------------------------------------------------------
# Le parent
# ---------------------------------------------------------------------------


async def test_parent_telecharge_le_bulletin_de_son_enfant(db, as_parent, released) -> None:
    """Le cas nominal cote parent."""
    pdf = await parent_service.get_child_bulletin_pdf(
        db, user_id=PARENT_USER_ID, student_id=STUDENT_ID, bulletin_id=OWN_PUBLISHED
    )
    assert pdf == FAKE_PDF


async def test_parent_refuse_l_enfant_d_une_autre_famille(db, as_parent, released) -> None:
    """Un enfant qui n'est pas le sien rend 404, pas 403."""
    with pytest.raises(NotFoundError) as exc:
        await parent_service.get_child_bulletin_pdf(
            db,
            user_id=PARENT_USER_ID,
            student_id=CLASSMATE_ID,
            bulletin_id=CLASSMATE_PUBLISHED,
        )
    assert exc.value.status_code == 404
    assert released == []


async def test_parent_refuse_un_bulletin_non_publie(db, as_parent, released) -> None:
    """Meme sur son propre enfant, un brouillon reste hors du portail."""
    with pytest.raises(NotFoundError) as exc:
        await parent_service.get_child_bulletin_pdf(
            db, user_id=PARENT_USER_ID, student_id=STUDENT_ID, bulletin_id=OWN_DRAFT
        )
    assert exc.value.status_code == 404


async def test_parent_ne_peut_pas_glisser_un_bulletin_etranger_sous_son_enfant(
    db, as_parent, released
) -> None:
    """L'identifiant de l'enfant est le sien, celui du bulletin ne l'est pas."""
    with pytest.raises(NotFoundError):
        await parent_service.get_child_bulletin_pdf(
            db,
            user_id=PARENT_USER_ID,
            student_id=STUDENT_ID,
            bulletin_id=CLASSMATE_PUBLISHED,
        )


async def test_parent_retenu_pour_impaye(db, as_parent, blocked) -> None:
    """Le parent non plus ne leve la retenue : elle se demande au secretariat."""
    with pytest.raises(HTTPException) as exc:
        await parent_service.get_child_bulletin_pdf(
            db, user_id=PARENT_USER_ID, student_id=STUDENT_ID, bulletin_id=OWN_PUBLISHED
        )
    assert exc.value.status_code == 402


# ---------------------------------------------------------------------------
# La garde elle-meme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bulletin_id",
    [OWN_DRAFT, CLASSMATE_PUBLISHED, UNKNOWN_BULLETIN],
    ids=["non-publie", "camarade", "inexistant"],
)
async def test_les_trois_refus_sont_indistincts(db, bulletin_id) -> None:
    """Les trois causes de refus rendent le meme message, sans rien reveler."""
    with pytest.raises(NotFoundError) as exc:
        await bulletin_access.ensure_owned_and_published(db, bulletin_id, student_id=STUDENT_ID)
    assert exc.value.detail == f"Bulletin with id {bulletin_id} not found"
