"""Tests du logo d'etablissement : POST et DELETE /admin/settings/logo.

Le logo suit le meme contrat que le tampon de signature : whitelist MIME,
plafond de 5 Mo, URL publique sous `/uploads/logos/`. Les tests deplacent la
racine d'upload vers un dossier temporaire fourni par pytest, jamais dans la
racine reelle : `UploadKind` derivant chaque dossier de cette racine, deplacer
la racine suffit a tout deplacer.

Depuis que le stockage persiste, l'endpoint doit aussi effacer le fichier qu'il
remplace ou retire, sans quoi chaque changement de logo laisserait un dechet
definitif dans le volume.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.services import admin_service

ROUTER = "app.routers.admin"
SVC = f"{ROUTER}.admin_service"
SERVICE = "app.services.admin_service"
UPLOADS = "app.core.uploads"

#: En-tete PNG suivi de quelques octets : le type declare suffit au controle,
#: le contenu n'est jamais decode.
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class _TransactionFactice:
    """Remplace `db.begin_nested()` : un `async with` qui ne fait rien."""

    async def __aenter__(self) -> "_TransactionFactice":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _ecole(logo_url: str | None = None) -> AsyncMock:
    """`get_school_settings` factice : le routeur ne lit que `logo_url`."""
    return AsyncMock(return_value=SimpleNamespace(id=1, logo_url=logo_url))


def _logo_existant(tmp_path: Path, nom: str) -> Path:
    """Pose un logo deja stocke sous la racine temporaire."""
    chemin = tmp_path / "logos" / nom
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(PNG)
    return chemin


# ---------------------------------------------------------------------------
# POST /admin/settings/logo
# ---------------------------------------------------------------------------


def test_upload_logo_accepte(client: TestClient, tmp_path: Path) -> None:
    """Un PNG valide atterrit sur le disque et l'URL publique est renvoyee."""
    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole()),
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

    ecrits = list((tmp_path / "logos").iterdir())
    assert len(ecrits) == 1
    assert ecrits[0].suffix == ".png"
    assert ecrits[0].read_bytes() == PNG


def test_upload_logo_efface_celui_qu_il_remplace(client: TestClient, tmp_path: Path) -> None:
    """Le logo precedent quitte le volume : sinon il y resterait pour toujours."""
    ancien = _logo_existant(tmp_path, "logo_abcd1234.png")

    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole("/uploads/logos/logo_abcd1234.png")),
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
    assert not ancien.exists()
    restants = [chemin.name for chemin in (tmp_path / "logos").iterdir()]
    assert restants == [Path(resp.json()["logo_url"]).name]


def test_upload_logo_type_refuse(client: TestClient, tmp_path: Path) -> None:
    """Un type hors whitelist est refuse avant toute ecriture."""
    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole()),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock) as enregistre,
    ):
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")},
        )

    assert resp.status_code == 400
    assert "Format invalide" in resp.json()["detail"]
    assert not (tmp_path / "logos").exists()
    enregistre.assert_not_awaited()


def test_upload_logo_trop_volumineux(client: TestClient, tmp_path: Path) -> None:
    """Au-dela de 5 Mo, rien n'est ecrit et le champ n'est pas modifie."""
    trop_gros = b"0" * (5 * 1024 * 1024 + 1)
    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole()),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock) as enregistre,
    ):
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.png", trop_gros, "image/png")},
        )

    assert resp.status_code == 400
    assert "trop volumineux" in resp.json()["detail"]
    assert not (tmp_path / "logos").exists()
    enregistre.assert_not_awaited()


def test_un_envoi_refuse_laisse_le_logo_en_place(client: TestClient, tmp_path: Path) -> None:
    """Un envoi rejete ne doit pas emporter le logo actuellement affiche."""
    actuel = _logo_existant(tmp_path, "logo_abcd1234.png")

    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole("/uploads/logos/logo_abcd1234.png")),
        patch(f"{SVC}.update_school_info", new_callable=AsyncMock),
    ):
        resp = client.post(
            "/admin/settings/logo",
            files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")},
        )

    assert resp.status_code == 400
    assert actuel.exists()


# ---------------------------------------------------------------------------
# DELETE /admin/settings/logo
# ---------------------------------------------------------------------------


def test_delete_logo_appelle_le_service(client: TestClient, tmp_path: Path) -> None:
    """La suppression delegue au service, sans corps de reponse."""
    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole()),
        patch(f"{SVC}.clear_school_logo", new_callable=AsyncMock) as efface,
    ):
        resp = client.delete("/admin/settings/logo")

    assert resp.status_code == 204
    assert resp.content == b""
    efface.assert_awaited_once()
    assert efface.await_args.kwargs["updated_by"] == 1


def test_delete_logo_efface_aussi_le_fichier(client: TestClient, tmp_path: Path) -> None:
    """Retirer le logo le retire du volume, pas seulement de la base."""
    fichier = _logo_existant(tmp_path, "logo_abcd1234.png")

    with (
        patch(f"{UPLOADS}.UPLOAD_ROOT", tmp_path),
        patch(f"{SVC}.get_school_settings", new=_ecole("/uploads/logos/logo_abcd1234.png")),
        patch(f"{SVC}.clear_school_logo", new_callable=AsyncMock),
    ):
        resp = client.delete("/admin/settings/logo")

    assert resp.status_code == 204
    assert not fichier.exists()


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
