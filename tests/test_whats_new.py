"""Les nouveautes ne doivent jamais ressembler a une panne.

C'est une fonctionnalite d'agrement : une cloche qui annonce ce qui a change.
Si le fichier qu'elle lit manque ou se corrompt, l'ecran doit dire « rien de
neuf » — faux, mais inoffensif — plutot que rendre une erreur qui ferait croire
a l'utilisateur que le portail est tombe.
"""

import json
from pathlib import Path

import pytest

from app.routers import whats_new


@pytest.mark.asyncio
async def test_un_fichier_absent_ne_fait_pas_une_panne(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whats_new, "_FLUX", Path("/introuvable/RELEASES.json"))

    flux = await whats_new.whats_new()

    assert flux["versions"] == []
    assert flux["current_version"] is None


@pytest.mark.asyncio
async def test_un_fichier_corrompu_ne_fait_pas_une_panne(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abime = tmp_path / "RELEASES.json"
    abime.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    monkeypatch.setattr(whats_new, "_FLUX", abime)

    assert (await whats_new.whats_new())["versions"] == []


@pytest.mark.asyncio
async def test_le_flux_est_rendu_tel_quel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L'ecran filtre par persona ; le serveur ne retire rien."""
    contenu = {
        "product": "klassci-college-backend",
        "current_version": "0.2.0",
        "versions": [{"version": "0.2.0", "sections": {"Fixed": [{"text": "un defaut"}]}}],
    }
    fichier = tmp_path / "RELEASES.json"
    fichier.write_text(json.dumps(contenu), encoding="utf-8")
    monkeypatch.setattr(whats_new, "_FLUX", fichier)

    assert await whats_new.whats_new() == contenu
