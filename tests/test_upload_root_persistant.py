"""La racine des fichiers televerses ne vit plus dans un dossier temporaire.

Les photos d'eleves, celles du personnel et le tampon de signature etaient
ecrits sous `/tmp`, que la recreation du conteneur vide : chaque redeploiement
les effacait. Ces tests verrouillent les proprietes qui evitent le retour du
probleme : une racine unique lue dans l'environnement, des sous-dossiers
partages par tous les modules d'ecriture, et des URL publiques inchangees.

S'y ajoute ce que la persistance a rendu necessaire. Tant que le stockage etait
jetable, un fichier remplace disparaissait avec le conteneur ; maintenant qu'il
survit, chaque remplacement laisserait un dechet definitif dans le volume si
personne n'effacait l'ancien.
"""

import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from app.core import uploads
from app.core.config import Settings
from app.core.uploads import (
    DOCUMENTS,
    KINDS,
    LOGOS,
    PHOTOS,
    SIGNATURES,
    UPLOAD_ROOT,
    delete_public_file,
)
from app.main import app
from app.utils.file_upload import DOCUMENT_UPLOAD_DIR
from app.utils.photo_upload import PHOTO_UPLOAD_DIR, read_capped


def test_racine_par_defaut_est_persistante() -> None:
    """Sans variable d'environnement, la racine est le point de montage du volume."""
    defaut = Settings.model_fields["UPLOAD_ROOT"].default
    assert defaut == "/app/uploads"
    assert not defaut.startswith("/tmp")


def test_sous_dossiers_derivent_tous_de_la_racine() -> None:
    """Photos, signatures, logos et documents sont des enfants de la meme racine."""
    assert PHOTOS.directory == UPLOAD_ROOT / "photos"
    assert SIGNATURES.directory == UPLOAD_ROOT / "signatures"
    assert LOGOS.directory == UPLOAD_ROOT / "logos"
    assert DOCUMENTS.directory == UPLOAD_ROOT / "documents"


def test_les_modules_d_ecriture_partagent_la_meme_racine() -> None:
    """Les alias historiques des helpers pointent sur les dossiers partages."""
    assert Path(PHOTO_UPLOAD_DIR) == PHOTOS.directory
    assert Path(DOCUMENT_UPLOAD_DIR) == DOCUMENTS.directory


@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.name)
def test_l_url_publique_et_le_dossier_ne_peuvent_pas_diverger(kind: uploads.UploadKind) -> None:
    """Le dossier ecrit et l'URL rendue designent le meme endroit, par construction.

    C'est la raison d'etre d'`UploadKind` : tenus separement, les deux finissaient
    par diverger, et un document sortait sans son image.
    """
    url = kind.public_url("f_abcd1234.png")
    chemin = kind.path_for("f_abcd1234.png")
    assert url == f"/uploads/{kind.directory.name}/f_abcd1234.png"
    assert chemin.parent == kind.directory
    assert url.endswith(chemin.name)


def test_deplacer_la_racine_deplace_tous_les_dossiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un test qui deplace `UPLOAD_ROOT` deplace tout, sans repatcher chaque module."""
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    for kind in KINDS:
        assert kind.directory == tmp_path / kind.name


def test_le_montage_uploads_sert_la_racine() -> None:
    """`/uploads` sert la racine partagee : les URL publiques ne changent pas."""
    montages = [route for route in app.routes if getattr(route, "name", "") == "uploads"]
    assert len(montages) == 1
    montage = montages[0]
    assert montage.path == "/uploads"
    fichiers = montage.app
    assert isinstance(fichiers, StaticFiles)
    assert Path(fichiers.directory) == UPLOAD_ROOT


# ---------------------------------------------------------------------------
# ensure_upload_dirs : bruyant la ou le volume compte, silencieux ailleurs
# ---------------------------------------------------------------------------


def _makedirs_refuse(*args: object, **kwargs: object) -> None:
    """Simule une racine absente ou en lecture seule, sur n'importe quel systeme."""
    raise OSError(13, "Permission denied")


@pytest.mark.parametrize("environnement", ["development", "test", "staging"])
def test_une_racine_non_creable_ne_bloque_pas_hors_production(
    monkeypatch: pytest.MonkeyPatch, environnement: str
) -> None:
    """Hors production, l'echec est un avertissement.

    Refuser de demarrer ici rendrait la suite de tests entierement rouge : le
    runner d'integration continue tourne en `test` et n'a pas de `/app`.
    """
    monkeypatch.setattr(uploads.settings, "APP_ENV", environnement)
    monkeypatch.setattr(uploads.os, "makedirs", _makedirs_refuse)

    uploads.ensure_upload_dirs()


@pytest.mark.parametrize("environnement", ["production", "prod", "PRODUCTION"])
def test_une_racine_non_creable_empeche_de_demarrer_en_production(
    monkeypatch: pytest.MonkeyPatch, environnement: str
) -> None:
    """En production, cela signifie un volume mal monte : mieux vaut ne pas demarrer.

    Un service qui demarre vert sert alors 404 sur chaque image et ne casse
    qu'au premier televersement, des jours plus tard, a l'impression d'un
    bulletin.
    """
    monkeypatch.setattr(uploads.settings, "APP_ENV", environnement)
    monkeypatch.setattr(uploads.os, "makedirs", _makedirs_refuse)

    with pytest.raises(OSError):
        uploads.ensure_upload_dirs()


# ---------------------------------------------------------------------------
# delete_public_file : le remplacement ne laisse pas de dechet dans le volume
# ---------------------------------------------------------------------------


def _fichier(kind: uploads.UploadKind, nom: str) -> Path:
    chemin = kind.path_for(nom)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(b"contenu")
    return chemin


def test_l_ancien_fichier_est_efface(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remplacer un logo efface celui qu'il remplace."""
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    ancien = _fichier(LOGOS, "logo_abcd1234.png")

    delete_public_file(LOGOS.public_url("logo_abcd1234.png"))

    assert not ancien.exists()


def test_seul_le_fichier_vise_est_efface(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Les voisins, et les autres sortes, ne sont pas touches."""
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    cible = _fichier(LOGOS, "logo_abcd1234.png")
    voisin = _fichier(LOGOS, "logo_ffff9999.png")
    photo = _fichier(PHOTOS, "logo_abcd1234.png")

    delete_public_file(LOGOS.public_url("logo_abcd1234.png"))

    assert not cible.exists()
    assert voisin.exists()
    assert photo.exists()


def test_une_url_absente_ou_vide_ne_fait_rien() -> None:
    """Un champ jamais renseigne n'est pas une erreur."""
    delete_public_file(None)
    delete_public_file("")


def test_un_fichier_deja_absent_ne_fait_rien(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L'URL en base peut designer un fichier deja disparu : ce n'est pas une erreur."""
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    LOGOS.directory.mkdir(parents=True, exist_ok=True)

    delete_public_file(LOGOS.public_url("logo_introuvable.png"))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/uploads/logos/logo_abcd1234.png",
        "/static/logo.png",
        "/uploads/logo.png",
        "/uploads/inconnu/logo_abcd1234.png",
    ],
)
def test_une_url_etrangere_est_ignoree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    """Seule une URL sous un dossier connu designe un fichier a effacer."""
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    temoin = _fichier(LOGOS, "logo_abcd1234.png")

    delete_public_file(url)

    assert temoin.exists()


@pytest.mark.parametrize(
    "suffixe",
    ["../photos/p_abcd1234.png", "sous/dossier/f.png", "../../evade.png"],
)
def test_une_url_qui_remonte_n_efface_rien(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffixe: str
) -> None:
    """L'URL vient de la base, on ne lui fait pas confiance pour autant.

    Seul un chemin qui retombe reellement a plat dans le dossier de sa sorte est
    efface : une remontee ne doit pas donner le droit de supprimer ailleurs.
    """
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path)
    voisine = _fichier(PHOTOS, "p_abcd1234.png")
    dehors = tmp_path / "evade.png"
    dehors.write_bytes(b"contenu")

    delete_public_file(f"{LOGOS.url_prefix}/{suffixe}")

    assert voisine.exists()
    assert dehors.exists()


# ---------------------------------------------------------------------------
# read_capped : refuser un envoi trop gros sans le charger entierement
# ---------------------------------------------------------------------------


def _envoi(taille: int) -> UploadFile:
    return UploadFile(file=io.BytesIO(b"0" * taille), filename="f.png")


async def test_un_envoi_sous_la_limite_est_lu_entierement() -> None:
    contenu = await read_capped(_envoi(1024), 5 * 1024)
    assert contenu == b"0" * 1024


async def test_un_envoi_a_la_limite_exacte_passe() -> None:
    """Le plafond est inclusif : refuser pile 5 Mo serait un refus arbitraire."""
    contenu = await read_capped(_envoi(4096), 4096)
    assert len(contenu) == 4096


async def test_un_envoi_au_dessus_de_la_limite_est_refuse() -> None:
    with pytest.raises(HTTPException) as erreur:
        await read_capped(_envoi(4097), 4096)
    assert erreur.value.status_code == 400
    assert "trop volumineux" in erreur.value.detail


async def test_le_plafond_est_annonce_en_mega_octets() -> None:
    """Le message dit la limite dans l'unite ou l'utilisateur l'a lue."""
    with pytest.raises(HTTPException) as erreur:
        await read_capped(_envoi(5 * 1024 * 1024 + 1), 5 * 1024 * 1024)
    assert "max 5 Mo" in erreur.value.detail
