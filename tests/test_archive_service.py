"""Corbeille — archiver d'abord, supprimer ensuite, toujours avec un motif."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.archive_service import (
    MIN_REASON_LENGTH,
    ArchivableKind,
    _clean_reason,
    ensure_archived_first,
    owns_user_account,
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


# ---------------------------------------------------------------------------
# Les cinq entités, la même mécanique
# ---------------------------------------------------------------------------


class _Personne:
    """Fiche minimale, telle que la mécanique la voit."""

    def __init__(self, archived: bool = False) -> None:
        self.id = 42
        self.first_name = "Aminata"
        self.last_name = "Traoré"
        self.archived_at = "2026-08-20" if archived else None
        self.archived_by = None
        self.archive_reason = None


def _kind_bidon(record: object) -> ArchivableKind:
    """Un type d'entité qui rend toujours la même fiche, sans base de données."""

    async def _charge(_db: object, _ident: int) -> object:
        return record

    async def _supprime(_db: object, _record: object) -> None:  # pragma: no cover
        raise AssertionError("la suppression ne doit pas être atteinte")

    # `_Personne` ne porte pas de `user_id` : la mecanique verra une fiche
    # sans compte de connexion, et n'aura donc rien a revoquer.
    return ArchivableKind(
        "essai", "La fiche", _Personne, _supprime, owns_user_account, load=_charge
    )


def test_le_registre_couvre_les_quatre_fiches_de_personnes() -> None:
    """Une sorte de fiche absente du registre perd ses trois gestes d'un coup.

    Elle resterait archivable par le filtre global, donc invisible, sans
    aucun moyen de l'en sortir."""
    from app.routers.archive import BINS
    from app.services.admin_service import PARENT_KIND, STAFF_KIND, STUDENT_KIND, TEACHER_KIND

    assert {b.kind for b in BINS.values()} == {
        STUDENT_KIND,
        TEACHER_KIND,
        STAFF_KIND,
        PARENT_KIND,
    }


def test_l_eleve_fige_son_identite_avant_de_quitter_les_ecrans() -> None:
    """Le filtre qui masque l'élève archivé le masque aussi derrière ses
    versements : sans ce recopiage, la colonne « Élève » du bordereau
    journalier se viderait du jour au lendemain."""
    from app.repositories import student_purge_repository as purge_repo
    from app.services.admin_service import STUDENT_KIND

    assert STUDENT_KIND.before_archive is purge_repo.freeze_student_identity_on_payments


async def test_le_prealable_court_avant_que_la_fiche_ne_soit_archivee() -> None:
    """L'ordre est le tout : figer une identité APRÈS l'archivage lirait une
    fiche déjà masquée."""
    from app.services.archive_service import archive_record

    fiche = _Personne(archived=False)
    vus: list[object] = []

    async def _prealable(_db: object, record: object) -> None:
        vus.append(getattr(record, "archived_at", None))

    kind = _kind_bidon(fiche)
    kind = ArchivableKind(
        kind.entity_type,
        kind.article,
        kind.model,
        kind.delete,
        kind.account_of,
        load=kind.load,
        before_archive=_prealable,
    )

    db = SimpleNamespace(commit=AsyncMock(), add=lambda _o: None)
    with (
        patch("app.services.archive_service.audit_log", new=AsyncMock()),
        patch("app.services.archive_service.notify", new=AsyncMock()),
    ):
        await archive_record(
            db,  # type: ignore[arg-type]
            kind,
            42,
            reason="Fiche créée deux fois par erreur",
            actor_id=1,
        )

    assert vus == [None], "le préalable doit voir la fiche encore visible"
    assert fiche.archived_at is not None


def test_toute_fiche_archivable_a_sa_place_dans_la_corbeille() -> None:
    """Une entité archivable sans gestes correspondants serait piégée dans la
    corbeille : masquée par le filtre, mais impossible à en sortir."""
    from app.core.archive_filter import _ARCHIVABLE
    from app.services.admin_service import PARENT_KIND, STAFF_KIND, STUDENT_KIND, TEACHER_KIND
    from app.services.enrollment_archive import ENROLLMENT_KIND

    couverts = {
        k.model for k in (STUDENT_KIND, TEACHER_KIND, STAFF_KIND, PARENT_KIND, ENROLLMENT_KIND)
    }
    assert couverts == set(_ARCHIVABLE)


def test_chaque_type_porte_un_libelle_lisible() -> None:
    """« La fiche 42 » ne dit rien à qui relit le journal six mois plus tard."""
    from app.services.admin_service import PARENT_KIND, STAFF_KIND, TEACHER_KIND

    fiche = _Personne()
    assert TEACHER_KIND.label(fiche) == "L'enseignant Traoré Aminata"
    assert STAFF_KIND.label(fiche) == "Le membre du personnel Traoré Aminata"
    assert PARENT_KIND.label(fiche) == "Le parent Traoré Aminata"


def test_une_inscription_se_nomme_par_son_eleve() -> None:
    """L'inscription n'a ni prénom ni nom : sans l'élève, la corbeille
    n'afficherait qu'un numéro."""
    from app.services.enrollment_archive import ENROLLMENT_KIND

    class _Inscription:
        id = 42
        student = _Personne()

    assert ENROLLMENT_KIND.label(_Inscription()) == "L'inscription de Traoré Aminata"

    class _Orpheline:
        id = 42
        student = None

    assert ENROLLMENT_KIND.label(_Orpheline()) == "L'inscription #42"


async def test_on_ne_purge_pas_une_fiche_qui_n_est_pas_passee_par_la_corbeille() -> None:
    """Le garde vaut pour toutes les entités, pas seulement pour l'élève."""
    from app.services.archive_service import purge_record

    with pytest.raises(HTTPException) as exc:
        await purge_record(
            None,  # type: ignore[arg-type]
            _kind_bidon(_Personne(archived=False)),
            42,
            reason="Fiche créée deux fois par erreur",
            actor_id=1,
        )
    assert exc.value.status_code == 409
    assert "corbeille" in exc.value.detail


async def test_archiver_exige_un_motif_quelle_que_soit_l_entite() -> None:
    """Le motif est demandé avant toute écriture : c'est ce qui garantit que
    le journal n'enregistre jamais une disparition sans explication."""
    from app.services.archive_service import archive_record

    with pytest.raises(HTTPException) as exc:
        await archive_record(
            None,  # type: ignore[arg-type]
            _kind_bidon(_Personne(archived=False)),
            42,
            reason="oups",
            actor_id=1,
        )
    assert exc.value.status_code == 422


async def test_une_fiche_deja_archivee_ne_se_rearchive_pas() -> None:
    from app.services.archive_service import archive_record

    with pytest.raises(HTTPException) as exc:
        await archive_record(
            None,  # type: ignore[arg-type]
            _kind_bidon(_Personne(archived=True)),
            42,
            reason="Fiche créée deux fois par erreur",
            actor_id=1,
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# L'écran de la corbeille
# ---------------------------------------------------------------------------


def test_la_corbeille_montre_toutes_les_sortes_de_fiches() -> None:
    """Un type oublié ici resterait invisible : archivable, mais introuvable."""
    from app.core.archive_filter import _ARCHIVABLE
    from app.services import recycle_bin

    modeles = {model for model, _ in recycle_bin._ARTICLES.values()}
    from app.models.enrollment import Enrollment

    modeles.add(Enrollment)
    assert modeles == set(_ARCHIVABLE)
    assert len(recycle_bin.ENTITY_TYPES) == len(_ARCHIVABLE)


def test_un_filtre_inconnu_est_refuse_plutot_que_vide() -> None:
    """Une corbeille vide se lit « rien à restaurer » : le mensonge serait
    tranquille alors que la cause est une faute de frappe."""
    from app.services.recycle_bin import ensure_known_entity_type

    assert ensure_known_entity_type(None) is None
    assert ensure_known_entity_type("enrollment") == "enrollment"

    with pytest.raises(HTTPException) as exc:
        ensure_known_entity_type("eleve")
    assert exc.value.status_code == 422
    assert "student" in exc.value.detail


def test_les_routes_de_la_corbeille_sont_toutes_montees() -> None:
    """Trois gestes exposés par entité, plus l'écran qui les rassemble."""
    from app.main import app

    chemins = {(tuple(sorted(r.methods)), r.path) for r in app.routes if hasattr(r, "methods")}
    attendus = [
        ("/admin/students/{student_id}",),
        ("/admin/teachers/{teacher_id}",),
        ("/admin/staff/{staff_id}",),
        ("/admin/parents/{parent_id}",),
        ("/enrollments/{enrollment_id}",),
    ]
    for (base,) in attendus:
        assert (("POST",), f"{base}/archive") in chemins, base
        assert (("POST",), f"{base}/restore") in chemins, base
        assert (("DELETE",), base) in chemins, base
    assert (("GET",), "/admin/archive") in chemins
