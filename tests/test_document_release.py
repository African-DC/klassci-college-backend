"""Porte de paiement des documents officiels — qui passe, qui est retenu, qui deroge."""

import pytest
from fastapi import HTTPException

from app.services import document_release_service as release
from app.services.document_release_service import ReleaseStatus
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

_OVERRIDE = "documents:release:override"


class _FakeDb:
    """Assez de surface pour que le service tourne sans base."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def audited(monkeypatch):
    """Capture les appels au journal d'audit au lieu de les ecrire."""
    calls: list[dict] = []

    async def _fake_audit(_db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(release, "audit_log", _fake_audit)
    return calls


def _stub_release(monkeypatch, *, blocked: bool, late: float = 0.0) -> None:
    async def _fake_evaluate(_db, _student_id):
        return ReleaseStatus(
            blocked=blocked,
            late_amount=late,
            enrollment_id=4 if blocked else None,
            academic_year_name="2025-2026",
        )

    monkeypatch.setattr(release, "evaluate_release", _fake_evaluate)


async def _run(db, *, may_override: bool, reason: str | None) -> None:
    await release.ensure_releasable(
        db,
        7,
        document_kind="bulletin",
        actor_id=1,
        may_override=may_override,
        override_reason=reason,
    )


# ---------------------------------------------------------------------------
# La porte
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_jour_le_document_sort(monkeypatch, audited) -> None:
    """Une famille a jour de ses echeances n'est jamais retenue."""
    _stub_release(monkeypatch, blocked=False)
    db = _FakeDb()
    await _run(db, may_override=False, reason=None)
    assert audited == []
    assert db.committed is False


@pytest.mark.asyncio
async def test_en_retard_le_document_est_retenu_avec_le_montant(monkeypatch, audited) -> None:
    """Le refus doit dire combien : « payez » sans montant n'aide personne."""
    _stub_release(monkeypatch, blocked=True, late=75000.0)
    with pytest.raises(HTTPException) as exc:
        await _run(_FakeDb(), may_override=False, reason=None)

    assert exc.value.status_code == 402, "402 et pas 403 : c'est un impaye, pas un droit manquant"
    detail = exc.value.detail
    assert detail["code"] == "DOCUMENT_BLOCKED_BY_ARREARS"
    assert detail["late_amount"] == 75000.0
    assert detail["can_override"] is False
    assert "75 000" in detail["message"]
    assert audited == []


@pytest.mark.asyncio
async def test_derogation_sans_motif_est_refusee(monkeypatch, audited) -> None:
    """Deroger sans dire pourquoi ne vaut guere mieux que pas de trace du tout."""
    _stub_release(monkeypatch, blocked=True, late=50000.0)
    for empty in (None, "", "   "):
        with pytest.raises(HTTPException) as exc:
            await _run(_FakeDb(), may_override=True, reason=empty)
        assert exc.value.status_code == 402
        # Le front doit pouvoir proposer le champ motif plutot qu'un mur.
        assert exc.value.detail["can_override"] is True
    assert audited == []


@pytest.mark.asyncio
async def test_derogation_motivee_passe_et_laisse_une_trace(monkeypatch, audited) -> None:
    _stub_release(monkeypatch, blocked=True, late=50000.0)
    db = _FakeDb()
    await _run(db, may_override=True, reason="  Cas social valide en conseil  ")

    assert len(audited) == 1
    entry = audited[0]
    assert entry["entity_type"] == "document_release_override"
    assert entry["user_id"] == 1
    assert entry["notes"] == "Cas social valide en conseil", "motif normalise"
    assert entry["new_values"]["document_kind"] == "bulletin"
    assert entry["new_values"]["late_amount"] == 50000.0
    assert db.committed is True, "la trace doit survivre meme si le PDF echoue ensuite"


# ---------------------------------------------------------------------------
# Qui peut deroger
# ---------------------------------------------------------------------------


def test_la_derogation_est_reservee_a_la_direction() -> None:
    """Constater la dette et l'effacer ne doivent pas etre la meme personne."""
    assert _OVERRIDE in {p["slug"] for p in ALL_PERMISSIONS}

    allowed = {"admin", "director"}
    for role, definition in ROLE_DEFINITIONS.items():
        has = _OVERRIDE in set(definition["permissions"])
        assert has is (role in allowed), f"{role} ne devrait pas pouvoir deroger"
