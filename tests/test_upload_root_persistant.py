"""La racine des fichiers televerses ne vit plus dans un dossier temporaire.

Les photos d'eleves, celles du personnel et le tampon de signature etaient
ecrits sous `/tmp`, que la recreation du conteneur vide : chaque redeploiement
les effacait. Ces tests verrouillent les trois proprietes qui evitent le retour
du probleme : une racine unique lue dans l'environnement, des sous-dossiers
partages par tous les modules d'ecriture, et des URL publiques inchangees.
"""

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.core.config import Settings
from app.core.uploads import (
    DOCUMENTS_DIR,
    LOGOS_DIR,
    PHOTOS_DIR,
    SIGNATURES_DIR,
    UPLOAD_ROOT,
)
from app.main import app
from app.routers import admin
from app.utils.file_upload import DOCUMENT_UPLOAD_DIR
from app.utils.photo_upload import PHOTO_UPLOAD_DIR


def test_racine_par_defaut_est_persistante() -> None:
    """Sans variable d'environnement, la racine est le point de montage du volume."""
    defaut = Settings.model_fields["UPLOAD_ROOT"].default
    assert defaut == "/app/uploads"
    assert not defaut.startswith("/tmp")


def test_sous_dossiers_derivent_tous_de_la_racine() -> None:
    """Photos, signatures, logos et documents sont des enfants de la meme racine."""
    assert PHOTOS_DIR == UPLOAD_ROOT / "photos"
    assert SIGNATURES_DIR == UPLOAD_ROOT / "signatures"
    assert LOGOS_DIR == UPLOAD_ROOT / "logos"
    assert DOCUMENTS_DIR == UPLOAD_ROOT / "documents"


def test_les_modules_d_ecriture_partagent_la_meme_racine() -> None:
    """Router admin et helpers d'upload pointent sur les dossiers partages."""
    assert admin.UPLOAD_DIR == PHOTOS_DIR
    assert admin.SIGNATURE_UPLOAD_DIR == SIGNATURES_DIR
    assert admin.LOGO_UPLOAD_DIR == LOGOS_DIR
    assert Path(PHOTO_UPLOAD_DIR) == PHOTOS_DIR
    assert Path(DOCUMENT_UPLOAD_DIR) == DOCUMENTS_DIR


def test_le_montage_uploads_sert_la_racine() -> None:
    """`/uploads` sert la racine partagee : les URL publiques ne changent pas."""
    montages = [route for route in app.routes if getattr(route, "name", "") == "uploads"]
    assert len(montages) == 1
    montage = montages[0]
    assert montage.path == "/uploads"
    fichiers = montage.app
    assert isinstance(fichiers, StaticFiles)
    assert Path(fichiers.directory) == UPLOAD_ROOT
