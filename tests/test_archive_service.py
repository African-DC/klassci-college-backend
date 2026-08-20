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


# ---------------------------------------------------------------------------
# Le filtre global
# ---------------------------------------------------------------------------


def test_toute_entite_archivable_est_couverte_par_le_filtre() -> None:
    """Une entité qui gagne la corbeille sans entrer dans cette liste
    réapparaîtrait dans tous les écrans : la corbeille promet l'inverse."""
    from app.core.archive_filter import _ARCHIVABLE
    from app.models.archivable import ArchivableMixin
    from app.models.enrollment import Enrollment
    from app.models.user import Parent, StaffProfile, Student, TeacherProfile

    attendues = {Student, Parent, TeacherProfile, StaffProfile, Enrollment}
    assert set(_ARCHIVABLE) == attendues

    for model in _ARCHIVABLE:
        assert issubclass(model, ArchivableMixin), f"{model.__name__} n'a pas les colonnes"
        for colonne in ("archived_at", "archived_by", "archive_reason"):
            assert colonne in model.__table__.columns


def test_la_colonne_de_corbeille_est_indexee() -> None:
    """Toutes les listes filtrent dessus : sans index, chaque écran ferait un
    balayage complet de la table."""
    from app.core.archive_filter import _ARCHIVABLE

    for model in _ARCHIVABLE:
        indexes = {tuple(c.name for c in idx.columns) for idx in model.__table__.indexes}
        assert ("archived_at",) in indexes, f"{model.__tablename__} : archived_at sans index"


def test_vider_la_corbeille_est_reserve_a_la_direction() -> None:
    """Archiver se rattrape, supprimer definitivement non : les deux gestes
    ne peuvent pas relever du meme droit."""
    from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

    slugs = {p["slug"] for p in ALL_PERMISSIONS}
    assert {"archive:read", "archive:purge"} <= slugs

    def perms(role: str) -> set[str]:
        return set(ROLE_DEFINITIONS[role]["permissions"])

    for role in ("admin", "director"):
        assert "archive:purge" in perms(role)

    for role in ("staff", "educator", "accountant", "cashier", "studies_director", "teacher"):
        assert "archive:purge" not in perms(role), f"{role} ne doit pas vider la corbeille"


def test_archiver_reste_sur_le_droit_de_suppression_existant() -> None:
    """Archiver n'introduit pas un droit de plus : c'est reversible, et le
    geste reste ouvert a qui pouvait deja supprimer.

    Aujourd'hui seul l'administrateur le peut. Ouvrir l'archivage au
    secretariat se fait en cochant `admin:students:delete` dans l'ecran Roles
    et permissions, sans toucher au code — mais c'est une decision d'ecole,
    pas un choix a prendre a sa place.
    """
    from app.services.tenants.permissions import ROLE_DEFINITIONS

    def perms(role: str) -> set[str]:
        return set(ROLE_DEFINITIONS[role]["permissions"])

    assert "admin:students:delete" in perms("admin")
    for role in ("staff", "educator"):
        assert "admin:students:delete" not in perms(role)
        assert "archive:purge" not in perms(role)
