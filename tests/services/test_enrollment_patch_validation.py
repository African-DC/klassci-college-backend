"""Valider par le formulaire d'édition, c'est valider.

Le formulaire d'édition renvoie le statut à chaque enregistrement. Passer à
« valide » par lui ne doit ni contourner le droit de valider, ni la garde de
versement, ni le refus des statuts terminaux : il passe par la validation
elle-même. Un statut déjà « valide » n'est pas une transition, et n'exige
rien : modifier les notes d'un dossier validé reste permis à qui peut le
modifier.

Les dépendances sont doublées ; on observe ce qui leur est passé.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessValidationError, PermissionDeniedError
from app.models.enrollment import EnrollmentStatus
from app.schemas.enrollment import EnrollmentUpdate
from app.services import enrollment_service, enrollment_validation


def _inscription(status: EnrollmentStatus) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1,
        student_id=42,
        class_id=3,
        academic_year_id=1,
        academic_year=SimpleNamespace(id=1, name="2025-2026"),
        student=SimpleNamespace(id=42, first_name="Awa", last_name="Traoré"),
        class_=SimpleNamespace(id=3, name="6ème A"),
        status=status,
        notes=None,
        created_by=1,
        enrollment_fees=[],
        assignment_status=None,
        assignment_decision_number=None,
        is_new_student=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def monde(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    etat: dict[str, Any] = {"inscription": _inscription(EnrollmentStatus.PROSPECT)}
    valider = AsyncMock()
    ecrire = AsyncMock()
    journal = AsyncMock()

    async def lire(_db: object, _id: int) -> SimpleNamespace:
        return etat["inscription"]

    monkeypatch.setattr(enrollment_service.repo, "get_enrollment_by_id", lire)
    monkeypatch.setattr(enrollment_service.repo, "update_enrollment", ecrire)
    monkeypatch.setattr(enrollment_validation, "appliquer_validation", valider)
    monkeypatch.setattr(enrollment_service, "audit_log", journal)
    etat.update(valider=valider, ecrire=ecrire, journal=journal)
    return etat


def _db() -> AsyncMock:
    db = AsyncMock()
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested)
    return db


@pytest.mark.asyncio
async def test_sans_le_droit_de_valider_l_edition_ne_valide_pas(monde: dict[str, Any]) -> None:
    with pytest.raises(PermissionDeniedError):
        await enrollment_service.update_enrollment(
            _db(), 1, EnrollmentUpdate(status="valide"), 7, peut_valider=False
        )
    monde["valider"].assert_not_called()
    monde["ecrire"].assert_not_called()


@pytest.mark.asyncio
async def test_avec_le_droit_l_edition_passe_par_la_validation(monde: dict[str, Any]) -> None:
    """La validation porte la garde de versement et le refus des statuts
    terminaux : c'est elle qui est appelée, pas une écriture de statut."""
    await enrollment_service.update_enrollment(
        _db(), 1, EnrollmentUpdate(status="valide"), 7, peut_valider=True
    )
    monde["valider"].assert_awaited_once()
    assert monde["valider"].call_args.args[1:] == (monde["inscription"], 7)
    # Le statut ne s'écrit que par la validation, et l'édition ne journalise
    # pas une seconde fois ce que la validation a déjà tracé.
    assert monde["ecrire"].call_args.kwargs["status"] is None
    monde["journal"].assert_not_called()


@pytest.mark.asyncio
async def test_les_autres_champs_s_ecrivent_apres_la_validation_sans_le_statut(
    monde: dict[str, Any],
) -> None:
    await enrollment_service.update_enrollment(
        _db(), 1, EnrollmentUpdate(status="valide", notes="dossier complet"), 7, peut_valider=True
    )
    monde["valider"].assert_awaited_once()
    ecrit = monde["ecrire"].call_args.kwargs
    assert ecrit["notes"] == "dossier complet"
    assert ecrit["status"] is None


@pytest.mark.asyncio
async def test_un_dossier_deja_valide_se_modifie_sans_le_droit_de_valider(
    monde: dict[str, Any],
) -> None:
    """Le formulaire renvoie « valide » : ce n'est pas une transition."""
    monde["inscription"] = _inscription(EnrollmentStatus.VALIDE)
    await enrollment_service.update_enrollment(
        _db(), 1, EnrollmentUpdate(status="valide", notes="complété"), 7, peut_valider=False
    )
    monde["valider"].assert_not_called()
    assert monde["ecrire"].call_args.kwargs["notes"] == "complété"


@pytest.mark.asyncio
async def test_une_classe_pleine_n_emporte_pas_une_validation_a_moitie(
    monde: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valider et changer de classe forment un seul geste : si la classe est
    pleine, rien n'est validé, au lieu d'un dossier validé derrière une erreur."""
    monkeypatch.setattr(
        enrollment_service.repo,
        "get_class_by_id_for_update",
        AsyncMock(return_value=SimpleNamespace(id=9, max_students=40)),
    )
    monkeypatch.setattr(
        enrollment_service.repo, "count_active_enrollments_for_class", AsyncMock(return_value=40)
    )
    with pytest.raises(BusinessValidationError):
        await enrollment_service.update_enrollment(
            _db(), 1, EnrollmentUpdate(status="valide", class_id=9), 7, peut_valider=True
        )
    monde["valider"].assert_not_called()
