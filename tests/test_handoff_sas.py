"""Le sas de depot n'est servi par rien, et c'est sa seule raison d'exister.

`UPLOAD_ROOT` est montee en entier sous `/uploads` par un `StaticFiles` brut :
sans authentification, sans cloisonnement de tenant, avec pour seul secret les
huit caracteres hexadecimaux du nom de fichier. Y deposer la photo qu'un
telephone vient d'envoyer et que personne n'a encore regardee la rendrait
publique.

Ces tests verrouillent la propriete qui l'empeche : la racine du sas n'est ni
`UPLOAD_ROOT`, ni un de ses sous-dossiers, ni servie par un montage. Le reste
verifie ce qui se passe autour : le nom qui fait l'aller-retour par Redis ne
peut pas devenir un chemin, et la promotion passe par la porte unique d'ecriture
plutot que d'en rouvrir une deuxieme.
"""

import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core import uploads
from app.core.config import Settings
from app.core.uploads import PHOTOS, UPLOAD_ROOT
from app.main import app
from app.utils import handoff_storage
from app.utils.handoff_storage import (
    HANDOFF_ROOT,
    delete_staged,
    promote_staged,
    read_staged,
    staged_path,
    write_staged,
)

JPEG = b"\xff\xd8\xff" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF" + b"0000" + b"WEBP" + b"0" * 64

SESSION = "abcDEF123"


def _envoi(contenu: bytes) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(contenu),
        filename="envoi.bin",
        headers=Headers({"content-type": "image/jpeg"}),
    )


@pytest.fixture
def sas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Un sas isole, distinct de la racine des televersements du meme test."""
    racine = tmp_path / "handoff"
    racine.mkdir()
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", racine)
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path / "uploads")
    return racine


# ---------------------------------------------------------------------------
# La propriete centrale : le sas n'est pas sous la racine servie
# ---------------------------------------------------------------------------


def test_le_sas_n_est_pas_la_racine_des_televersements() -> None:
    """Deux racines, pas une. La confusion serait la fuite."""
    assert HANDOFF_ROOT != UPLOAD_ROOT


def test_le_sas_n_est_pas_un_sous_dossier_de_la_racine_servie() -> None:
    """Le montage sert TOUTE la racine : un sous-dossier serait public aussi.

    Le ranger sous `UPLOAD_ROOT` par commodite suffirait a publier, sans
    authentification, des photos de mineurs en attente de validation.
    """
    assert UPLOAD_ROOT not in HANDOFF_ROOT.parents
    assert HANDOFF_ROOT not in UPLOAD_ROOT.parents


def test_les_racines_par_defaut_sont_deux_chemins_distincts() -> None:
    """La separation tient dans les valeurs par defaut, pas dans un .env bien rempli."""
    sas = Settings.model_fields["HANDOFF_ROOT"].default
    televerses = Settings.model_fields["UPLOAD_ROOT"].default
    assert sas != televerses
    assert not sas.startswith(f"{televerses}/")


def test_aucun_montage_ne_sert_le_sas() -> None:
    """L'application ne monte que `/uploads`. Le sas n'a pas d'URL du tout.

    C'est le test qui verrait quelqu'un ajouter un `app.mount` « pour
    l'apercu » : l'apercu passe par un endpoint authentifie, jamais par un
    montage statique.
    """
    servies = [
        Path(getattr(route.app, "directory", ""))
        for route in app.routes
        if getattr(route, "name", "") and hasattr(getattr(route, "app", None), "directory")
    ]
    assert servies, "aucun montage statique trouve : le test ne verifie plus rien"
    for racine in servies:
        assert racine != HANDOFF_ROOT
        assert HANDOFF_ROOT not in racine.parents
        assert racine not in HANDOFF_ROOT.parents


# ---------------------------------------------------------------------------
# Ecrire, relire, effacer
# ---------------------------------------------------------------------------


async def test_l_envoi_est_relu_octet_pour_octet(sas: Path) -> None:
    nom = await write_staged(_envoi(JPEG), session_id=SESSION, extension="jpg", max_bytes=1024)

    assert read_staged(nom) == JPEG
    assert (sas / nom).exists()


async def test_le_nom_porte_la_session(sas: Path) -> None:
    """Le balayeur des orphelins travaille sur le disque, pas sur les cles Redis."""
    nom = await write_staged(_envoi(JPEG), session_id=SESSION, extension="jpg", max_bytes=1024)

    assert nom.startswith(f"{SESSION}_")
    assert nom.endswith(".jpg")


async def test_l_extension_vient_du_type_valide_pas_du_nom_envoye(sas: Path) -> None:
    """Le telephone a nomme son fichier `envoi.bin` : le sas n'en tient aucun compte."""
    nom = await write_staged(_envoi(WEBP), session_id=SESSION, extension="webp", max_bytes=1024)

    assert nom.endswith(".webp")


async def test_un_envoi_trop_gros_est_refuse(sas: Path) -> None:
    """Meme plafond que partout : `read_capped` s'arrete au premier octet de trop."""
    with pytest.raises(HTTPException) as erreur:
        await write_staged(_envoi(b"0" * 4097), session_id=SESSION, extension="jpg", max_bytes=4096)

    assert erreur.value.status_code == 400
    assert "trop volumineux" in erreur.value.detail


@pytest.mark.parametrize(
    ("contenu", "extension"),
    [
        (b"<?php system($_GET[0]); ?>", "jpg"),
        (b"MZ\x90\x00" + b"0" * 64, "png"),
        (JPEG, "png"),
        (PNG, "jpg"),
        (b"RIFF" + b"0000" + b"AVI " + b"0" * 64, "webp"),
        (JPEG, "pdf"),
        (b"", "jpg"),
    ],
)
async def test_un_fichier_qui_ment_sur_son_format_n_entre_pas(
    sas: Path, contenu: bytes, extension: str
) -> None:
    """Le type declare vient du telephone : ses octets doivent le confirmer.

    Sans ce controle, un fichier annonce `image/jpeg` mais portant tout autre
    chose serait promu tel quel sous `/uploads/photos/`, servi par le montage
    statique, avec une extension qui ment sur son contenu.
    """
    with pytest.raises(HTTPException) as erreur:
        await write_staged(_envoi(contenu), session_id=SESSION, extension=extension, max_bytes=1024)

    assert erreur.value.status_code == 400
    assert not list(sas.iterdir()), "un fichier refuse ne doit rien laisser sur le disque"


async def test_une_extension_inconnue_du_sas_n_entre_pas(sas: Path) -> None:
    """La liste des formats est close : un oubli ferme la porte, il ne l'ouvre pas."""
    with pytest.raises(HTTPException) as erreur:
        await write_staged(_envoi(JPEG), session_id=SESSION, extension="svg", max_bytes=1024)

    assert erreur.value.status_code == 400


def test_relire_un_depot_disparu_donne_404(sas: Path) -> None:
    """Le sas vit dans un volume qu'un redeploiement recree : l'absence est normale."""
    with pytest.raises(HTTPException) as erreur:
        read_staged("abc_12345678.jpg")

    assert erreur.value.status_code == 404


async def test_effacer_deux_fois_ne_leve_pas(sas: Path) -> None:
    """Confirmation, reprise, revocation et balayage effacent le meme fichier."""
    nom = await write_staged(_envoi(JPEG), session_id=SESSION, extension="jpg", max_bytes=1024)

    delete_staged(nom)
    delete_staged(nom)
    delete_staged(None)

    assert not (sas / nom).exists()


# ---------------------------------------------------------------------------
# Le nom revient de Redis : c'est une donnee, pas une constante du programme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nom",
    [
        "../uploads/photos/vol.jpg",
        "..\\evade.jpg",
        "sous/dossier/f.jpg",
        "/etc/passwd",
        "abc_12345678.jpg.exe",
        "abc_1234.jpg",
        "",
    ],
)
def test_un_nom_qui_n_est_pas_le_notre_est_refuse(sas: Path, nom: str) -> None:
    """Redis est partage par tous les etablissements ; ce nom en revient.

    Le refuser avant de toucher au disque est ce qui empeche une cle trafiquee
    d'atteindre un `unlink` ou une lecture hors du sas.
    """
    with pytest.raises(HTTPException) as erreur:
        staged_path(nom)

    assert erreur.value.status_code == 400


def test_un_nom_qui_remonte_n_efface_rien(sas: Path, tmp_path: Path) -> None:
    """Un chemin qui sort du sas est ignore, pas suivi."""
    dehors = tmp_path / "temoin.jpg"
    dehors.write_bytes(b"contenu")

    delete_staged("../temoin.jpg")

    assert dehors.exists()


# ---------------------------------------------------------------------------
# La promotion : une seule porte d'ecriture, celle de `photo_upload`
# ---------------------------------------------------------------------------


async def test_la_promotion_rend_une_url_qui_sert_les_octets_deposes(sas: Path) -> None:
    """L'URL rendue designe le fichier reellement ecrit dans la sorte visee.

    C'est la promesse de `save_bytes`, et la raison pour laquelle la promotion
    l'appelle au lieu de renommer le fichier elle-meme : un chemin d'ecriture
    parallele finirait par annoncer une URL et ecrire ailleurs.
    """
    nom = await write_staged(_envoi(JPEG), session_id=SESSION, extension="jpg", max_bytes=1024)

    url = promote_staged(nom, kind=PHOTOS, prefix="42")

    assert url.startswith(f"{PHOTOS.url_prefix}/")
    assert PHOTOS.path_for(url[len(f"{PHOTOS.url_prefix}/") :]).read_bytes() == JPEG


async def test_la_promotion_vide_le_sas(sas: Path) -> None:
    """Un fichier promu n'a plus rien a faire dans le sas : il serait un orphelin."""
    nom = await write_staged(_envoi(JPEG), session_id=SESSION, extension="jpg", max_bytes=1024)

    promote_staged(nom, kind=PHOTOS, prefix="42")

    assert not (sas / nom).exists()


async def test_la_promotion_garde_l_extension_du_depot(sas: Path) -> None:
    nom = await write_staged(_envoi(PNG), session_id=SESSION, extension="png", max_bytes=1024)

    url = promote_staged(nom, kind=PHOTOS, prefix="42")

    assert url.endswith(".png")


def test_promouvoir_un_depot_disparu_donne_404(sas: Path) -> None:
    """La session a expire, le balayeur est passe : rien a promouvoir."""
    with pytest.raises(HTTPException) as erreur:
        promote_staged("abc_12345678.jpg", kind=PHOTOS, prefix="42")

    assert erreur.value.status_code == 404


# ---------------------------------------------------------------------------
# ensure_handoff_dir : bruyant la ou le volume compte, silencieux ailleurs
# ---------------------------------------------------------------------------


def _makedirs_refuse(*args: object, **kwargs: object) -> None:
    raise OSError(13, "Permission denied")


@pytest.mark.parametrize("environnement", ["development", "test", "staging"])
def test_un_sas_non_creable_ne_bloque_pas_hors_production(
    monkeypatch: pytest.MonkeyPatch, environnement: str
) -> None:
    """`/app/handoff` n'existe ni sur un poste de developpement ni sur un runner."""
    monkeypatch.setattr(handoff_storage.settings, "APP_ENV", environnement)
    monkeypatch.setattr(handoff_storage.os, "makedirs", _makedirs_refuse)

    handoff_storage.ensure_handoff_dir()


@pytest.mark.parametrize("environnement", ["production", "prod", "PRODUCTION"])
def test_un_sas_non_creable_empeche_de_demarrer_en_production(
    monkeypatch: pytest.MonkeyPatch, environnement: str
) -> None:
    """En production, cela signifie un volume mal monte.

    L'echec au demarrage se voit ; un premier depot qui echoue un jour de
    rentree, sur le telephone de quelqu'un, ne se voit pas.
    """
    monkeypatch.setattr(handoff_storage.settings, "APP_ENV", environnement)
    monkeypatch.setattr(handoff_storage.os, "makedirs", _makedirs_refuse)

    with pytest.raises(OSError):
        handoff_storage.ensure_handoff_dir()
