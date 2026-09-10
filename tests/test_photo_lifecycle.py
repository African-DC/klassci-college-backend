"""Poser une photo : la trace qui manquait, et le fichier qu'on n'effaçait pas.

Deux dettes réglées ensemble, parce que la reprise par code 2D les transforme
toutes les deux en problèmes réels.

**Le journal.** Les trois `update_*_photo` recevaient `updated_by` et ne s'en
servaient pas : la photo d'un élève, la donnée la plus personnelle d'une fiche,
était la seule mutation sensible du produit sans une ligne d'audit. Avec le
dépôt par téléphone, l'écart devient plus grave encore : l'image est prise par
un appareil qui n'a pas de compte, et sans `ip_address` rien ne dirait d'où.

**Le fichier.** `delete_public` n'était câblé que sur le logo et le tampon. Les
photos s'écrasaient, l'ancien fichier restant sur le volume pour toujours.
Chaque « Reprendre » étant une image de plus, la fuite grandirait exactement à
la vitesse du succès de la fonctionnalité.

Ces tests portent sur `photo_lifecycle`, où les deux gestes vivent désormais
ensemble : les séparer est précisément ce qui les a fait oublier.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core import uploads
from app.core.audit import AuditAction
from app.core.uploads import PHOTOS
from app.services.photo_lifecycle import replace_photo

MODULE = "app.services.photo_lifecycle"


class Fiche:
    """Le strict minimum du protocole : une fiche n'est ici qu'une colonne."""

    def __init__(self, photo_url: str | None = None) -> None:
        self.photo_url = photo_url


@pytest.fixture
def racine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path / "uploads")
    dossier = PHOTOS.directory
    dossier.mkdir(parents=True)
    return dossier


@pytest.fixture
def journal() -> Any:
    with patch(f"{MODULE}.audit_log", new_callable=AsyncMock) as ecrire:
        yield ecrire


def _photo(racine: Path, nom: str) -> str:
    (racine / nom).write_bytes(b"\xff\xd8\xffimage")
    return PHOTOS.public_url(nom)


# ---------------------------------------------------------------------------
# La trace
# ---------------------------------------------------------------------------


async def test_poser_une_photo_ecrit_une_ligne_d_audit(journal: Any, racine: Path) -> None:
    """`updated_by` arrivait jusqu'ici et n'allait nulle part."""
    fiche = Fiche(_photo(racine, "42_aaaaaaaa.jpg"))
    db = AsyncMock()

    await replace_photo(
        db,
        fiche,
        entity_type="student",
        entity_id=42,
        photo_url=PHOTOS.public_url("42_bbbbbbbb.jpg"),
        updated_by=7,
    )

    journal.assert_awaited_once()
    ecrit = journal.await_args.kwargs
    assert ecrit["entity_type"] == "student"
    assert ecrit["entity_id"] == 42
    assert ecrit["action"] == AuditAction.UPDATE
    assert ecrit["user_id"] == 7
    assert ecrit["old_values"]["photo_url"].endswith("42_aaaaaaaa.jpg")
    assert ecrit["new_values"]["photo_url"].endswith("42_bbbbbbbb.jpg")
    db.commit.assert_awaited_once()


async def test_la_trace_dit_d_ou_la_photo_est_arrivee(journal: Any, racine: Path) -> None:
    """L'opérateur confirme depuis son écran ; la photo, elle, vient d'ailleurs.

    L'adresse est celle du téléphone, capturée au dépôt. C'est la seule trace de
    qui a réellement appuyé sur le déclencheur.
    """
    await replace_photo(
        AsyncMock(),
        Fiche(),
        entity_type="student",
        entity_id=42,
        photo_url=PHOTOS.public_url("42_bbbbbbbb.jpg"),
        updated_by=7,
        ip_address="41.66.0.9",
        notes="photo reçue par reprise QR, session xyz",
    )

    ecrit = journal.await_args.kwargs
    assert ecrit["ip_address"] == "41.66.0.9"
    assert "reprise QR" in ecrit["notes"]


async def test_retirer_une_photo_se_journalise_aussi(journal: Any, racine: Path) -> None:
    """Retirer la photo d'un élève est une mutation comme une autre."""
    fiche = Fiche(_photo(racine, "42_aaaaaaaa.jpg"))

    await replace_photo(
        AsyncMock(),
        fiche,
        entity_type="student",
        entity_id=42,
        photo_url=None,
        updated_by=7,
    )

    assert fiche.photo_url is None
    assert journal.await_args.kwargs["new_values"]["photo_url"] is None


# ---------------------------------------------------------------------------
# L'ancien fichier
# ---------------------------------------------------------------------------


async def test_la_photo_remplacee_quitte_le_disque(journal: Any, racine: Path) -> None:
    """Sans cela, chaque remplacement laisse un déchet définitif sur le volume."""
    ancienne = _photo(racine, "42_aaaaaaaa.jpg")
    nouvelle = _photo(racine, "42_bbbbbbbb.jpg")

    await replace_photo(
        AsyncMock(),
        Fiche(ancienne),
        entity_type="student",
        entity_id=42,
        photo_url=nouvelle,
        updated_by=7,
    )

    assert not (racine / "42_aaaaaaaa.jpg").exists()
    assert (racine / "42_bbbbbbbb.jpg").exists()


async def test_l_ancien_fichier_survit_a_un_echec_d_ecriture(journal: Any, racine: Path) -> None:
    """La colonne désigne encore l'ancienne photo : l'effacer donnerait une fiche cassée.

    Un fichier orphelin après un commit réussi se rattrape — le balayage ou un
    remplacement suivant s'en chargent. Une fiche qui pointe vers un fichier
    supprimé, non.
    """
    ancienne = _photo(racine, "42_aaaaaaaa.jpg")
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("la base a lâché")

    with pytest.raises(RuntimeError):
        await replace_photo(
            db,
            Fiche(ancienne),
            entity_type="student",
            entity_id=42,
            photo_url=PHOTOS.public_url("42_bbbbbbbb.jpg"),
            updated_by=7,
        )

    assert (racine / "42_aaaaaaaa.jpg").exists()


async def test_reposer_la_meme_url_n_efface_rien_et_ne_journalise_rien(
    journal: Any, racine: Path
) -> None:
    """Le second appel effacerait le fichier que la colonne désigne encore."""
    url = _photo(racine, "42_aaaaaaaa.jpg")

    await replace_photo(
        AsyncMock(),
        Fiche(url),
        entity_type="student",
        entity_id=42,
        photo_url=url,
        updated_by=7,
    )

    assert (racine / "42_aaaaaaaa.jpg").exists()
    journal.assert_not_awaited()


async def test_une_url_etrangere_n_atteint_aucun_fichier(
    journal: Any, racine: Path, tmp_path: Path
) -> None:
    """La garde de `delete_public` était écrite pour le logo, sans jamais servir ici.

    Une URL qui ne désigne pas un fichier de la sorte « photos », à plat dans
    son dossier, est ignorée en silence — elle ne remonte pas, elle ne sort pas.
    """
    temoin = tmp_path / "temoin.jpg"
    temoin.write_bytes(b"contenu")

    for etrangere in (
        "/uploads/photos/../../../temoin.jpg",
        "/uploads/logos/logo_aaaaaaaa.jpg",
        "https://ailleurs.example/photo.jpg",
        "temoin.jpg",
    ):
        await replace_photo(
            AsyncMock(),
            Fiche(etrangere),
            entity_type="student",
            entity_id=42,
            photo_url=None,
            updated_by=7,
        )

    assert temoin.exists()
