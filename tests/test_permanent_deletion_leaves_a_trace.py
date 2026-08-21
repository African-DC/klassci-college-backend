"""Une suppression définitive laisse une trace hors du logiciel.

`archive_service` s'ouvre sur cette promesse : « un mail sort du logiciel : si
quelqu'un efface une trace, il n'efface pas une boîte de réception. » Elle ne
tenait que pour l'élève, seul cas qui n'empruntait pas le chemin partagé ;
l'enseignant, le personnel et le parent partaient sans un mot.
"""

from dataclasses import dataclass

import pytest

from app.services import archive_service
from app.services.deletion import Dependent


@dataclass
class _Fiche:
    id: int = 7
    first_name: str = "Awa"
    last_name: str = "Kone"
    archived_at: object = "2026-08-20"
    archived_by: object = 1
    archive_reason: object = "doublon de saisie"


class _Session:
    """Juste ce qu'il faut de session pour dérouler purge_record."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self):  # noqa: ANN201 - contexte asynchrone minimal
        class _Nested:
            async def __aenter__(self_inner) -> None:
                return None

            async def __aexit__(self_inner, *_exc: object) -> bool:
                return False

        return _Nested()


@pytest.fixture
def kind() -> tuple[archive_service.ArchivableKind, list[int]]:
    """Rend le type archivable et la liste témoin de ce qui a été détruit."""
    detruit: list[int] = []

    async def _delete(_db: object, fiche: _Fiche) -> tuple[Dependent, ...]:
        detruit.append(fiche.id)
        return (Dependent("inscription", "inscriptions", 3, blocking=False),)

    async def _load(_db: object, _ident: int) -> _Fiche:
        return _Fiche()

    return (
        archive_service.ArchivableKind("teacher", "L'enseignant", _Fiche, _delete, load=_load),
        detruit,
    )


@pytest.mark.asyncio
async def test_la_suppression_definitive_envoie_le_courriel(
    kind: tuple[archive_service.ArchivableKind, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    type_archivable, _ = kind
    envoyes: list[archive_service.ArchiveOutcome] = []

    async def _audit(*_a: object, **_k: object) -> None:
        return None

    async def _notify(_db: object, outcome: archive_service.ArchiveOutcome) -> None:
        envoyes.append(outcome)

    monkeypatch.setattr(archive_service, "audit_log", _audit)
    monkeypatch.setattr(archive_service, "notify", _notify)

    await archive_service.purge_record(
        _Session(), type_archivable, 7, reason="fiche creee en double le 12 aout", actor_id=1
    )

    assert len(envoyes) == 1
    assert envoyes[0].permanent is True
    assert envoyes[0].entity_type == "teacher"
    # Le courriel dit ce qui est parti avec la fiche, pas seulement qu'elle est partie.
    assert envoyes[0].carried_away == ("3 inscriptions",)


@pytest.mark.asyncio
async def test_le_motif_est_exige_avant_toute_destruction(
    kind: tuple[archive_service.ArchivableKind, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un motif trop court doit refuser AVANT que quoi que ce soit ne parte."""
    type_archivable, detruit = kind

    async def _audit(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(archive_service, "audit_log", _audit)

    with pytest.raises(Exception) as capture:
        await archive_service.purge_record(_Session(), type_archivable, 7, reason="ok", actor_id=1)

    assert getattr(capture.value, "status_code", None) == 422
    assert detruit == []
