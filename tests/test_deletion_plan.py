"""Suppression en cascade — l'inventaire d'abord, l'argent jamais."""

import pytest
from fastapi import HTTPException

from app.services.deletion import DeletionPlan, Dependent, ensure_deletable


def _plan(*dependents: Dependent) -> DeletionPlan:
    return DeletionPlan(entity_label="« Scolarité »", dependents=dependents)


def test_sans_dependance_on_supprime_sans_rien_demander() -> None:
    ensure_deletable(_plan(), cascade=False)


def test_les_dependances_a_zero_ne_declenchent_rien() -> None:
    """Un compteur à zéro ne doit pas provoquer une confirmation vide."""
    ensure_deletable(_plan(Dependent("montant configuré", "montants configurés", 0)), cascade=False)


def test_le_premier_clic_annonce_ce_qui_sera_emporte() -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_deletable(
            _plan(
                Dependent("montant configuré", "montants configurés", 3),
                Dependent("frais d'élève", "frais d'élèves", 47),
            ),
            cascade=False,
        )
    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "DELETE_HAS_DEPENDENTS"
    assert detail["can_cascade"] is True
    assert "3 montants configurés" in detail["message"]
    assert "47 frais d'élèves" in detail["message"]
    assert detail["dependents"] == [
        {"label": "montants configurés", "count": 3, "blocking": False},
        {"label": "frais d'élèves", "count": 47, "blocking": False},
    ]


def test_confirmee_la_cascade_passe() -> None:
    ensure_deletable(_plan(Dependent("montant configuré", "montants configurés", 3)), cascade=True)


def test_l_argent_bloque_meme_confirme() -> None:
    """Un versement encaissé qui perd sa contrepartie est un trou comptable
    que le journal d'audit ne rattrapera pas."""
    for cascade in (False, True):
        with pytest.raises(HTTPException) as exc:
            ensure_deletable(
                _plan(
                    Dependent("montant configuré", "montants configurés", 3),
                    Dependent("versement imputé", "versements imputés", 2, blocking=True),
                ),
                cascade=cascade,
            )
        detail = exc.value.detail
        assert detail["code"] == "DELETE_BLOCKED"
        assert detail["can_cascade"] is False
        assert "2 versements imputés" in detail["message"]


def test_le_singulier_est_accorde() -> None:
    """« 1 montants configurés » à l'écran d'une école, ça se remarque."""
    with pytest.raises(HTTPException) as exc:
        ensure_deletable(
            _plan(Dependent("montant configuré", "montants configurés", 1)), cascade=False
        )
    assert "1 montant configuré" in exc.value.detail["message"]
    assert "1 montants" not in exc.value.detail["message"]


def test_l_enumeration_se_lit_en_francais() -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_deletable(
            _plan(
                Dependent("montant configuré", "montants configurés", 3),
                Dependent("frais d'élève", "frais d'élèves", 47),
                Dependent("option", "options", 2),
            ),
            cascade=False,
        )
    assert "3 montants configurés, 47 frais d'élèves et 2 options" in exc.value.detail["message"]


def test_le_verbe_s_accorde_avec_ce_qui_bloque() -> None:
    """« 1 versement imputé en dépendent » se lit mal sur l'écran d'une école."""
    with pytest.raises(HTTPException) as exc:
        ensure_deletable(
            _plan(Dependent("versement imputé", "versements imputés", 1, blocking=True)),
            cascade=True,
        )
    assert "1 versement imputé en dépend." in exc.value.detail["message"]

    with pytest.raises(HTTPException) as exc:
        ensure_deletable(
            _plan(Dependent("versement imputé", "versements imputés", 4, blocking=True)),
            cascade=True,
        )
    assert "4 versements imputés en dépendent." in exc.value.detail["message"]
