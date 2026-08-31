"""Tests du logo d'etablissement : POST et DELETE /admin/settings/logo.

Le logo suit le meme contrat que le tampon de signature : whitelist MIME,
plafond de 5 Mo, URL publique sous `/uploads/logos/`. Les tests ecrivent dans
un dossier temporaire fourni par pytest, jamais dans la racine d'upload reelle.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.services import admin_service

ROUTER = "app.routers.admin"
SVC = f"{ROUTER}.admin_service"
SERVICE = "app.services.admin_service"

#: En-tete PNG suivi de quelques octets : le type declare suffit au controle,
#: le contenu n'est jamais decode.
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class _TransactionFactice:
    """Remplace `db.begin_nested()` : un `async with` qui ne fait rien."""

    async def __aenter__(self) -> "_TransactionFactice":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


# ---------------------------------------------------------------------------
# POST /admin/settings/logo
# ---------------------------------------------------------------------------


def test_upload_logo_accepte(client: TestClient, tmp_path: Path) -> None:
    """Un PNG valide atterrit sur le disque et l'URL publique est renvoyee."""
    with (
        patch(f"{ROUTER}.LOGO_UPLOAD_DIR", tmp_path),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock) as enregistre,
    ):
        enregistre.side_effect = lambda db, data, updated_by: SimpleNamespace(
            logo_url=data.logo_url
        )
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        )

    assert resp.status_code == 200
    assert resp.json()["logo_url"].startswith("/uploads/logos/logo_")

    ecrits = list(tmp_path.iterdir())
    assert len(ecrits) == 1
    assert ecrits[0].suffix == ".png"
    assert ecrits[0].read_bytes() == PNG


def test_upload_logo_type_refuse(client: TestClient, tmp_path: Path) -> None:
    """Un type hors whitelist est refuse avant toute ecriture."""
    with (
        patch(f"{ROUTER}.LOGO_UPLOAD_DIR", tmp_path),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock) as enregistre,
    ):
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")},
        )

    assert resp.status_code == 400
    assert "Format invalide" in resp.json()["detail"]
    assert list(tmp_path.iterdir()) == []
    enregistre.assert_not_awaited()


def test_upload_logo_trop_volumineux(client: TestClient, tmp_path: Path) -> None:
    """Au-dela de 5 Mo, rien n'est ecrit et le champ n'est pas modifie."""
    trop_gros = b"0" * (5 * 1024 * 1024 + 1)
    with (
        patch(f"{ROUTER}.LOGO_UPLOAD_DIR", tmp_path),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock) as enregistre,
    ):
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.png", trop_gros, "image/png")},
        )

    assert resp.status_code == 400
    assert "trop volumineux" in resp.json()["detail"]
    assert list(tmp_path.iterdir()) == []
    enregistre.assert_not_awaited()


# ---------------------------------------------------------------------------
# DELETE /admin/settings/logo
# ---------------------------------------------------------------------------


def test_delete_logo_appelle_le_service(client: TestClient) -> None:
    """La suppression delegue au service, sans corps de reponse."""
    with patch(f"{SVC}.clear_school_logo", new_callable=AsyncMock) as efface:
        resp = client.delete("/admin/settings/logo")

    assert resp.status_code == 204
    assert resp.content == b""
    efface.assert_awaited_once()
    assert efface.await_args.kwargs["updated_by"] == 1


async def test_clear_school_logo_vide_le_champ() -> None:
    """Le service remet `logo_url` a NULL et laisse une trace d'audit."""
    ecole = SimpleNamespace(id=1, logo_url="/uploads/logos/logo_abcd1234.png")
    db = AsyncMock()
    db.begin_nested = Mock(return_value=_TransactionFactice())

    with (
        patch(f"{SERVICE}.get_school_settings", new_callable=AsyncMock, return_value=ecole),
        patch(f"{SERVICE}.audit_log", new_callable=AsyncMock) as journal,
    ):
        resultat = await admin_service.clear_school_logo(db, updated_by=1)

    assert ecole.logo_url is None
    assert resultat is ecole
    journal.assert_awaited_once()
    assert journal.await_args.kwargs["new_values"] == {"logo_url": None}


async def test_clear_school_logo_sans_logo_ne_journalise_rien() -> None:
    """Supprimer un logo absent est sans effet, donc sans entree d'audit."""
    ecole = SimpleNamespace(id=1, logo_url=None)
    db = AsyncMock()
    db.begin_nested = Mock(return_value=_TransactionFactice())

    with (
        patch(f"{SERVICE}.get_school_settings", new_callable=AsyncMock, return_value=ecole),
        patch(f"{SERVICE}.audit_log", new_callable=AsyncMock) as journal,
    ):
        resultat = await admin_service.clear_school_logo(db, updated_by=1)

    assert resultat is ecole
    journal.assert_not_awaited()
