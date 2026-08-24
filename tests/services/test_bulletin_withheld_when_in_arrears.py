"""La consultation d'un bulletin suit la meme porte que son telechargement.

Une famille en retard sur ses tranches voit que le bulletin existe, pas ce
qu'il dit. Ses notes publiees, elles, restent lisibles : la retenue porte sur
le document de synthese, pas sur le releve des notes.

Les tests appellent les fonctions du service pour de vrai. Seules deux
frontieres sont remplacees : la lecture des bulletins en base et le calcul de
l'echeancier, qui sont testes ailleurs.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services import bulletin_visibility
from app.services import parent_portal_service as parent_service
from app.services import student_portal_service as student_service
from app.services.bulletin_visibility import Withholding
from app.services.document_release_service import ReleaseStatus
from tests.bulletin_portal_decor import (
    OWN_PUBLISHED,
    BulletinsDb,
    close_payment_gate,
    install_pdf_factory,
    login_student,
)

STUDENT_ID = 2
USER_ID = 3
STUDENT_USER_ID = 3
LATE_AMOUNT = 45000.0


# ---------------------------------------------------------------------------
# Decor
# ---------------------------------------------------------------------------


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bulletin:
    """Un bulletin publie, tel que le repository le rend au service."""

    def __init__(self, bulletin_id: int, trimester: int) -> None:
        self.id = bulletin_id
        self.trimester = trimester
        self.average = Decimal("14.30")
        self.rank = 3
        self.mention = "Bien"
        self.class_ = _Named("6e A")
        self.academic_year = _Named("2025-2026")
        self.file_url = f"/media/bulletins/{bulletin_id}.pdf"
        self.generated_at = None
        self.is_published = True


class _Student:
    id = STUDENT_ID


class _Parent:
    id = 1


BULLETINS = [_Bulletin(51, 1), _Bulletin(52, 2)]


@pytest.fixture
def portal_reads(monkeypatch):
    """Les deux portails lisent les memes bulletins, sans base."""

    async def _bulletins(_db, _student_id):
        return BULLETINS

    async def _student(_db, _user_id):
        return _Student()

    async def _parent(_db, _user_id):
        return _Parent()

    async def _link(_db, _parent_id, _student_id):
        return object()

    monkeypatch.setattr(student_service.repo, "get_published_bulletins_for_student", _bulletins)
    monkeypatch.setattr(student_service.repo, "get_student_by_user_id", _student)
    monkeypatch.setattr(parent_service.repo, "get_student_bulletins", _bulletins)
    monkeypatch.setattr(parent_service.repo, "get_parent_by_user_id", _parent)
    monkeypatch.setattr(parent_service.repo, "get_parent_student_link", _link)


def _set_gate(monkeypatch, *, blocked: bool, late: float = 0.0) -> list[int]:
    """Fixe l'etat de l'echeancier. Rend les eleves sur lesquels il est interroge."""
    asked: list[int] = []

    async def _fake_evaluate(_db, student_id):
        asked.append(student_id)
        return ReleaseStatus(
            blocked=blocked,
            late_amount=late,
            enrollment_id=4 if blocked else None,
            academic_year_name="2025-2026",
        )

    for module in (student_service, parent_service):
        monkeypatch.setattr(module.document_release_service, "evaluate_release", _fake_evaluate)
    return asked


# ---------------------------------------------------------------------------
# Famille a jour : elle voit tout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_jour_l_eleve_voit_le_contenu_du_bulletin(monkeypatch, portal_reads) -> None:
    _set_gate(monkeypatch, blocked=False)

    response = await student_service.get_bulletins(None, USER_ID)

    assert response.total == 2
    first = response.items[0]
    assert first.average == Decimal("14.30")
    assert first.rank == 3
    assert first.mention == "Bien"
    assert first.file_url == "/media/bulletins/51.pdf"
    assert first.is_withheld is False
    assert first.withheld_reason is None
    assert first.withheld_amount is None


@pytest.mark.asyncio
async def test_a_jour_le_parent_voit_le_contenu_du_bulletin(monkeypatch, portal_reads) -> None:
    _set_gate(monkeypatch, blocked=False)

    response = await parent_service.get_child_bulletins(None, USER_ID, STUDENT_ID)

    first = response.bulletins[0]
    assert first.average == Decimal("14.30")
    assert first.rank == 3
    assert first.mention == "Bien"
    assert first.is_withheld is False


# ---------------------------------------------------------------------------
# Famille en retard : le bulletin est annonce, pas divulgue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_en_retard_l_eleve_voit_le_bulletin_annonce_mais_vide(
    monkeypatch, portal_reads
) -> None:
    """Le bulletin reste dans la liste, son contenu tombe a None."""
    _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    response = await student_service.get_bulletins(None, USER_ID)

    assert response.total == 2, "la liste ne se vide pas : la famille doit voir qu'ils existent"
    first = response.items[0]

    # Ce qui identifie le bulletin reste lisible.
    assert first.id == 51
    assert first.trimester == 1
    assert first.class_name == "6e A"
    assert first.academic_year_name == "2025-2026"

    # Ce qu'il dit de l'eleve disparait.
    assert first.average is None
    assert first.rank is None
    assert first.mention is None
    assert first.file_url is None, "le lien du PDF est un contenu : il tombe avec le reste"


@pytest.mark.asyncio
async def test_en_retard_la_retenue_dit_pourquoi_et_combien(monkeypatch, portal_reads) -> None:
    """« Indisponible » sans montant ni chemin n'aide personne."""
    _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    response = await student_service.get_bulletins(None, USER_ID)
    first = response.items[0]

    assert first.is_withheld is True
    assert first.withheld_amount == LATE_AMOUNT
    assert first.withheld_reason == (
        "Bulletin du 1er trimestre indisponible : 45 000 FCFA en retard "
        "sur l'échéancier. Rapprochez-vous du secrétariat."
    )


@pytest.mark.asyncio
async def test_en_retard_chaque_motif_nomme_son_trimestre(monkeypatch, portal_reads) -> None:
    """Trois motifs identiques a l'ecran se liraient comme un bug d'affichage."""
    _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    response = await student_service.get_bulletins(None, USER_ID)

    assert "1er trimestre" in (response.items[0].withheld_reason or "")
    assert "2e trimestre" in (response.items[1].withheld_reason or "")


@pytest.mark.asyncio
async def test_en_retard_le_parent_voit_la_meme_retenue(monkeypatch, portal_reads) -> None:
    """Le parent ne doit pas contourner la retenue en ouvrant son propre portail."""
    _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    response = await parent_service.get_child_bulletins(None, USER_ID, STUDENT_ID)

    assert len(response.bulletins) == 2
    first = response.bulletins[0]
    assert first.average is None
    assert first.rank is None
    assert first.mention is None
    assert first.is_withheld is True
    assert first.withheld_amount == LATE_AMOUNT
    assert "45 000 FCFA" in (first.withheld_reason or "")


@pytest.mark.asyncio
async def test_l_echeancier_n_est_interroge_qu_une_fois_par_liste(
    monkeypatch, portal_reads
) -> None:
    """Deux bulletins, un seul calcul : la retenue vaut pour l'eleve, pas par ligne."""
    asked = _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    await student_service.get_bulletins(None, USER_ID)

    assert asked == [STUDENT_ID]


@pytest.mark.asyncio
async def test_en_retard_le_telechargement_reste_refuse(monkeypatch) -> None:
    """La consultation retenue et le PDF refuse sont la meme regle, aux deux bouts.

    Vider la liste sans garder le 402 laisserait le PDF sortir a qui connait
    l'adresse ; garder le 402 sans vider la liste afficherait le contenu qu'on
    refuse d'imprimer. Ce test tient les deux ensemble.
    """
    install_pdf_factory(monkeypatch)
    login_student(monkeypatch)
    close_payment_gate(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await student_service.get_bulletin_pdf(
            BulletinsDb(), user_id=STUDENT_USER_ID, bulletin_id=OWN_PUBLISHED
        )

    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "DOCUMENT_BLOCKED_BY_ARREARS"


# ---------------------------------------------------------------------------
# Les notes publiees restent accessibles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_en_retard_les_notes_publiees_restent_lisibles(monkeypatch) -> None:
    """La porte s'applique au bulletin, jamais au releve des notes."""
    _set_gate(monkeypatch, blocked=True, late=LATE_AMOUNT)

    class _Subject:
        name = "Mathématiques"

    class _Evaluation:
        id = 11
        title = "Devoir de maison"
        type = "devoir"
        date = date(2026, 1, 15)
        coefficient = 2
        trimester = 1
        subject = _Subject()

    class _Grade:
        id = 90
        value = Decimal("15.50")
        status = "saisie"
        evaluation = _Evaluation()

    async def _student(_db, _user_id):
        return _Student()

    async def _grades(_db, _student_id, **_kwargs):
        return [_Grade()]

    monkeypatch.setattr(student_service.repo, "get_student_by_user_id", _student)
    monkeypatch.setattr(student_service.repo, "get_grades_for_student", _grades)

    response = await student_service.get_grades(None, USER_ID)

    assert response.total == 1
    assert response.items[0].value == Decimal("15.50")
    assert response.items[0].evaluation.subject_name == "Mathématiques"


# ---------------------------------------------------------------------------
# Ecole sans echeancier : personne n'est retenu
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sans_tranche_configuree_rien_n_est_retenu(monkeypatch, portal_reads) -> None:
    """Aucune echeance definie, aucun retard possible : accuser serait faux.

    `resolve_schedule` rend un echeancier sans ligne quand l'ecole n'a pose
    aucune grille, et `compute_arrears` en tire un retard nul. La porte reste
    donc ouverte, et c'est ce que ce test verrouille au niveau du portail.
    """
    _set_gate(monkeypatch, blocked=False)

    response = await student_service.get_bulletins(None, USER_ID)

    first = response.items[0]
    assert first.is_withheld is False
    assert first.average == Decimal("14.30")
    assert first.file_url is not None


# ---------------------------------------------------------------------------
# La redaction elle-meme
# ---------------------------------------------------------------------------


def test_le_contenu_masque_vaut_none_jamais_zero() -> None:
    """Un zero se lirait « il a eu zero de moyenne » : c'est une calomnie."""
    withheld = Withholding(active=True, late_amount=LATE_AMOUNT)

    result = withheld.apply(
        {"trimester": 1, "average": Decimal("14.30"), "rank": 3, "mention": "Bien"}
    )

    assert result["average"] is None
    assert result["rank"] is None
    assert result["mention"] is None
    assert 0 not in (result["average"], result["rank"])


def test_les_champs_de_retenue_sont_toujours_rendus() -> None:
    """Un ecran qui doit deviner si un champ absent vaut « a jour » choisira mal."""
    open_gate = Withholding(active=False, late_amount=0.0)

    result = open_gate.apply({"trimester": 2, "average": Decimal("9.00")})

    assert result["is_withheld"] is False
    assert result["withheld_reason"] is None
    assert result["withheld_amount"] is None
    assert result["average"] == Decimal("9.00")


def test_tout_champ_de_contenu_liste_est_masque() -> None:
    """Le garde porte sur une liste nommee, pas sur les champs qu'on a en tete."""
    withheld = Withholding(active=True, late_amount=LATE_AMOUNT)
    block = {"trimester": 3, **dict.fromkeys(bulletin_visibility.CONTENT_FIELDS, "quelque chose")}

    result = withheld.apply(block)

    for field in bulletin_visibility.CONTENT_FIELDS:
        assert result[field] is None, f"{field} devrait etre masque"


def test_la_porte_ouverte_partagee_ne_retient_rien() -> None:
    """Les composeurs internes de PDF passent par la, leur acces etant deja tranche."""
    assert bulletin_visibility.OPEN.active is False
    assert bulletin_visibility.OPEN.apply({"trimester": 1, "average": 12})["average"] == 12
