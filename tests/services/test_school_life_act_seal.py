"""Référence de sceau des actes de vie scolaire.

La lignée de sceaux est indexée sur (type de document, référence), et finaliser
une révision périme toutes les précédentes de la même référence. Deux actes
distincts qui partagent leur référence s'invalident donc mutuellement : le
professeur qui scanne le Datamatrix du billet du premier trimestre lit
« document remplacé » parce qu'un second billet a été émis en février.

Ces tests fixent les deux règles qui l'empêchent : la référence porte
l'identifiant de l'acte, et le matricule est exigé.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BusinessValidationError
from app.services.school_life import _common

_ISSUED_AT = datetime(2026, 2, 16, 9, 30, 0)


def _context(matricule: str | None = "M-2026-0041") -> SimpleNamespace:
    """Contexte élève tel que `load_student_context` le rend."""
    return SimpleNamespace(
        student=SimpleNamespace(
            id=42,
            first_name="Aminata",
            last_name="Traoré",
            enrollment_number=matricule,
        ),
        student_name="Aminata Traoré",
        class_name="6ème B",
        academic_year_name="2025-2026",
    )


async def _reference(
    monkeypatch: pytest.MonkeyPatch,
    *,
    act_id: int | None,
    matricule: str | None = "M-2026-0041",
    ref_prefix: str = "BAZ",
) -> str:
    """Émet un sceau factice et renvoie la référence effectivement signée."""
    captured: dict[str, Any] = {}

    async def _fake_build_verification(_db: object, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"reference": kwargs["reference"]}

    monkeypatch.setattr(_common, "build_verification", _fake_build_verification)
    await _common.issue_act_seal(
        AsyncMock(),
        document_type="annulation_zero",
        ref_prefix=ref_prefix,
        context=_context(matricule),
        issued_at=_ISSUED_AT,
        source_data={},
        act_id=act_id,
    )
    return str(captured["reference"])


# ---------------------------------------------------------------------------
# L'identifiant de l'acte
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_reference_porte_lidentifiant_de_lacte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = await _reference(monkeypatch, act_id=7)
    assert reference == "BAZ-2026-M-2026-0041-7"


@pytest.mark.asyncio
async def test_deux_actes_du_meme_eleve_ne_partagent_pas_leur_lignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un élève peut légitimement avoir deux billets d'annulation de zéro dans
    l'année — un par trimestre. Le second ne doit pas périmer le premier."""
    trimestre_1 = await _reference(monkeypatch, act_id=7)
    trimestre_2 = await _reference(monkeypatch, act_id=19)
    assert trimestre_1 != trimestre_2


@pytest.mark.asyncio
async def test_deux_convocations_du_meme_parent_ne_partagent_pas_leur_lignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    premiere = await _reference(monkeypatch, act_id=3, ref_prefix="CVP")
    seconde = await _reference(monkeypatch, act_id=4, ref_prefix="CVP")
    assert premiere != seconde


@pytest.mark.asyncio
async def test_un_acte_sans_registre_garde_une_lignee_par_eleve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La demande de dossier scolaire n'a pas de registre : une version
    corrigée doit bien remplacer la précédente, l'ancien courrier n'ayant
    plus cours."""
    reference = await _reference(monkeypatch, act_id=None, ref_prefix="DDS")
    assert reference == "DDS-2026-M-2026-0041"


@pytest.mark.asyncio
async def test_le_meme_acte_reimprime_garde_sa_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Réimprimer un billet perdu ne doit pas ouvrir une nouvelle lignée : le
    papier déjà remis reste vérifiable."""
    premiere = await _reference(monkeypatch, act_id=7)
    reimpression = await _reference(monkeypatch, act_id=7)
    assert premiere == reimpression


# ---------------------------------------------------------------------------
# Le matricule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("matricule", [None, "", "   "])
async def test_un_eleve_sans_matricule_est_refuse(
    monkeypatch: pytest.MonkeyPatch, matricule: str | None
) -> None:
    """Sans matricule, tous les élèves non matriculés partageaient la même
    référence, donc la même lignée : un rendu échoué bloquait alors le guichet
    entier pendant cinq minutes, pour tout le monde."""
    with pytest.raises(BusinessValidationError) as excinfo:
        await _reference(monkeypatch, act_id=7, matricule=matricule)
    message = str(excinfo.value)
    assert "matricule" in message
    assert "Aminata Traoré" in message


@pytest.mark.asyncio
async def test_deux_eleves_ne_peuvent_plus_partager_une_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    premiere = await _reference(monkeypatch, act_id=7, matricule="M-0001")
    seconde = await _reference(monkeypatch, act_id=8, matricule="M-0002")
    assert premiere != seconde
    assert "M-0001" in premiere
    assert "M-0002" in seconde
