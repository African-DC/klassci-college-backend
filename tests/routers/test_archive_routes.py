"""Corbeille — les douze points d'entrée, servis par un seul chemin de code.

Ces tests appellent les URL telles que le frontend les appelle déjà. Ils
existent d'abord pour ça : la mécanique a été rassemblée, les adresses ne
doivent pas avoir bougé d'un caractère, sinon l'écran « Corbeille » et les
boutons « Archiver » tombent en production.

Ils vérifient ensuite les deux choses qu'un regroupement met en danger : que
chaque geste reste derrière le droit qui était le sien, et que le motif ne
voyage plus dans l'URL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.routers import archive as archive_router
from app.services import admin_service

MOCK_USER = TokenData(user_id=7, tenant_id="local", email="admin@college.ci")

MOTIF = "Fiche créée deux fois lors de la rentrée"

#: entité → (segment d'URL, KIND attendu, droit qui ouvre archive/restore)
CAS = [
    ("student", "students", admin_service.STUDENT_KIND, "admin:students:delete"),
    ("teacher", "teachers", admin_service.TEACHER_KIND, "admin:teachers:delete"),
    ("staff", "staff", admin_service.STAFF_KIND, "admin:staff:delete"),
    ("parent", "parents", admin_service.PARENT_KIND, "admin:parents:delete"),
]

PURGE_PERMISSION = "archive:purge"


@contextmanager
def _client(*, refuse: str | None = None) -> Iterator[TestClient]:
    """Client authentifié. `refuse` retire un seul droit, tous les autres passent.

    Les droits sont servis par la vraie dépendance `require_permission`, qui
    va les lire là où elle les lit en production : la matrice en base. Simuler
    la matrice plutôt que la dépendance est ce qui donne au test le droit de
    dire quelque chose sur les permissions.
    """
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()

    async def _check(_db: object, _user_id: int, slug: str) -> bool:
        return slug != refuse

    try:
        with patch(
            "app.repositories.permission_repository.check_user_permission",
            new=AsyncMock(side_effect=_check),
        ):
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Les URL n'ont pas bougé
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("entite", "segment", "kind", "_perm"), CAS)
def test_archiver_passe_par_l_url_historique(
    entite: str, segment: str, kind: object, _perm: str
) -> None:
    """`POST /admin/students/42/archive` — l'adresse que le frontend appelle."""
    with _client() as client:
        with patch.object(
            archive_router.archive_service, "archive_record", new_callable=AsyncMock
        ) as archive_record:
            resp = client.post(f"/admin/{segment}/42/archive", json={"reason": MOTIF})

    assert resp.status_code == 204, resp.text
    archive_record.assert_awaited_once()
    args, kwargs = archive_record.await_args
    assert args[1] is kind, f"{entite} archivé avec le mauvais type de fiche"
    assert args[2] == 42
    assert kwargs["reason"] == MOTIF
    assert kwargs["actor_id"] == MOCK_USER.user_id


@pytest.mark.parametrize(("entite", "segment", "kind", "_perm"), CAS)
def test_restaurer_passe_par_l_url_historique(
    entite: str, segment: str, kind: object, _perm: str
) -> None:
    with _client() as client:
        with patch.object(
            archive_router.archive_service, "restore_record", new_callable=AsyncMock
        ) as restore_record:
            resp = client.post(f"/admin/{segment}/42/restore")

    assert resp.status_code == 204, resp.text
    args, kwargs = restore_record.await_args
    assert args[1] is kind, f"{entite} restauré avec le mauvais type de fiche"
    assert args[2] == 42
    assert kwargs["actor_id"] == MOCK_USER.user_id


@pytest.mark.parametrize(("entite", "segment", "kind", "_perm"), CAS)
def test_supprimer_definitivement_passe_par_l_url_historique(
    entite: str, segment: str, kind: object, _perm: str
) -> None:
    with _client() as client:
        with patch.object(
            archive_router.archive_service, "purge_record", new_callable=AsyncMock
        ) as purge_record:
            resp = client.request("DELETE", f"/admin/{segment}/42", json={"reason": MOTIF})

    assert resp.status_code == 204, resp.text
    args, kwargs = purge_record.await_args
    assert args[1] is kind, f"{entite} supprimé avec le mauvais type de fiche"
    assert args[2] == 42
    assert kwargs["reason"] == MOTIF


# ---------------------------------------------------------------------------
# Le motif ne voyage plus dans l'URL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("_entite", "segment", "_kind", "_perm"), CAS)
def test_le_motif_en_parametre_d_url_n_est_plus_accepte(
    _entite: str, segment: str, _kind: object, _perm: str
) -> None:
    """Une URL finit dans les journaux d'accès du serveur et chez les
    intermédiaires. « Élève exclu pour vol » n'a rien à y faire."""
    with _client() as client:
        with patch.object(
            archive_router.archive_service, "purge_record", new_callable=AsyncMock
        ) as purge_record:
            resp = client.request("DELETE", f"/admin/{segment}/42?reason={MOTIF}")

    assert resp.status_code == 422
    purge_record.assert_not_awaited()


@pytest.mark.parametrize(("_entite", "segment", "_kind", "_perm"), CAS)
def test_un_motif_trop_court_est_refuse_avant_toute_destruction(
    _entite: str, segment: str, _kind: object, _perm: str
) -> None:
    with _client() as client:
        with patch.object(
            archive_router.archive_service, "purge_record", new_callable=AsyncMock
        ) as purge_record:
            resp = client.request("DELETE", f"/admin/{segment}/42", json={"reason": "ok"})

    assert resp.status_code == 422
    purge_record.assert_not_awaited()


# ---------------------------------------------------------------------------
# Chaque geste garde le droit qui était le sien
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("_entite", "segment", "_kind", "permission"), CAS)
def test_archiver_exige_le_droit_de_suppression_de_l_entite(
    _entite: str, segment: str, _kind: object, permission: str
) -> None:
    """Le droit est lu en base par `require_permission`, jamais déduit d'un rôle."""
    with _client(refuse=permission) as client:
        with patch.object(
            archive_router.archive_service, "archive_record", new_callable=AsyncMock
        ) as archive_record:
            resp = client.post(f"/admin/{segment}/42/archive", json={"reason": MOTIF})

    assert resp.status_code == 403
    archive_record.assert_not_awaited()


@pytest.mark.parametrize(("_entite", "segment", "_kind", "permission"), CAS)
def test_restaurer_exige_le_meme_droit_qu_archiver(
    _entite: str, segment: str, _kind: object, permission: str
) -> None:
    with _client(refuse=permission) as client:
        with patch.object(
            archive_router.archive_service, "restore_record", new_callable=AsyncMock
        ) as restore_record:
            resp = client.post(f"/admin/{segment}/42/restore")

    assert resp.status_code == 403
    restore_record.assert_not_awaited()


@pytest.mark.parametrize(("_entite", "segment", "_kind", "_perm"), CAS)
def test_supprimer_definitivement_exige_le_droit_de_vider_la_corbeille(
    _entite: str, segment: str, _kind: object, _perm: str
) -> None:
    """Archiver se rattrape, supprimer non : les deux gestes n'ont jamais
    relevé du même droit, et le regroupement ne les a pas confondus."""
    with _client(refuse=PURGE_PERMISSION) as client:
        with patch.object(
            archive_router.archive_service, "purge_record", new_callable=AsyncMock
        ) as purge_record:
            resp = client.request("DELETE", f"/admin/{segment}/42", json={"reason": MOTIF})

    assert resp.status_code == 403
    purge_record.assert_not_awaited()


@pytest.mark.parametrize(("_entite", "segment", "_kind", "permission"), CAS)
def test_vider_la_corbeille_ne_suffit_pas_a_archiver(
    _entite: str, segment: str, _kind: object, permission: str
) -> None:
    """Et réciproquement : le droit de purger ne doit pas ouvrir l'archivage
    d'une entité dont on n'a pas le droit de suppression."""
    with _client(refuse=PURGE_PERMISSION) as client:
        with patch.object(
            archive_router.archive_service, "archive_record", new_callable=AsyncMock
        ) as archive_record:
            resp = client.post(f"/admin/{segment}/42/archive", json={"reason": MOTIF})

    assert resp.status_code == 204
    archive_record.assert_awaited_once()


# ---------------------------------------------------------------------------
# L'écran de la corbeille reste servi par le même routeur
# ---------------------------------------------------------------------------


def test_l_ecran_corbeille_repond_toujours_sur_admin_archive() -> None:
    """La route littérale ne doit jamais être avalée par une route
    paramétrique du même routeur."""
    with _client() as client:
        with patch.object(
            archive_router.recycle_bin, "list_bin", new_callable=AsyncMock
        ) as list_bin:
            list_bin.return_value = {"items": [], "total": 0, "page": 1, "size": 50}
            resp = client.get("/admin/archive")

    assert resp.status_code == 200, resp.text
    list_bin.assert_awaited_once()
