"""Corbeille — archiver d'abord, supprimer ensuite, toujours avec un motif."""

import pytest
from fastapi import HTTPException

from app.services.archive_service import (
    MIN_REASON_LENGTH,
    _clean_reason,
    ensure_archived_first,
)


class _Fiche:
    def __init__(self, archived: bool = False) -> None:
        self.id = 7
        self.archived_at = "2026-08-20" if archived else None
        self.archived_by = None
        self.archive_reason = None


# ---------------------------------------------------------------------------
# Le motif
# ---------------------------------------------------------------------------


def test_un_motif_trop_court_est_refuse() -> None:
    """« ok » ou « test » ne dit rien à celui qui relira le journal."""
    for court in (None, "", "   ", "ok", "test"):
        with pytest.raises(HTTPException) as exc:
            _clean_reason(court)
        assert exc.value.status_code == 422
        assert str(MIN_REASON_LENGTH) in exc.value.detail


def test_le_motif_est_normalise() -> None:
    assert _clean_reason("  Doublon de la fiche 42  ") == "Doublon de la fiche 42"


def test_le_message_previent_que_le_motif_sera_diffuse() -> None:
    """Personne ne doit découvrir après coup que son motif est parti par mail."""
    with pytest.raises(HTTPException) as exc:
        _clean_reason("non")
    assert "journal" in exc.value.detail
    assert "courriel" in exc.value.detail


# ---------------------------------------------------------------------------
# L'ordre des gestes
# ---------------------------------------------------------------------------


def test_on_ne_supprime_pas_une_fiche_encore_visible() -> None:
    """Le passage par la corbeille est ce qui laisse le temps de se raviser."""
    with pytest.raises(HTTPException) as exc:
        ensure_archived_first(_Fiche(archived=False), label="L'élève Traoré Aminata")
    assert exc.value.status_code == 409
    assert "corbeille" in exc.value.detail
    assert "Traoré Aminata" in exc.value.detail


def test_une_fiche_deja_dans_la_corbeille_peut_etre_supprimee() -> None:
    ensure_archived_first(_Fiche(archived=True), label="L'élève Traoré Aminata")
