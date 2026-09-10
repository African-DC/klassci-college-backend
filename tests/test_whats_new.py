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

    assert flux["sections"] == {}
    assert flux["version"] is None
    assert flux["total"] == 0


@pytest.mark.asyncio
async def test_un_fichier_corrompu_ne_fait_pas_une_panne(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abime = tmp_path / "RELEASES.json"
    abime.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    monkeypatch.setattr(whats_new, "_FLUX", abime)

    assert (await whats_new.whats_new())["sections"] == {}


def _pose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contenu: dict) -> None:
    fichier = tmp_path / "RELEASES.json"
    fichier.write_text(json.dumps(contenu), encoding="utf-8")
    monkeypatch.setattr(whats_new, "_FLUX", fichier)


@pytest.mark.asyncio
async def test_seule_la_version_la_plus_recente_est_rendue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """« Nouveautes » repond a « depuis ma derniere visite », pas a « raconte-moi tout »."""
    _pose(
        tmp_path,
        monkeypatch,
        {
            "product": "klassci-college-backend",
            "generated_at": "2026-09-02T00:00:00Z",
            "versions": [
                {"version": "0.2.0", "released": True, "sections": {"Fixed": [{"text": "recent"}]}},
                {"version": "0.1.0", "released": True, "sections": {"Fixed": [{"text": "vieux"}]}},
            ],
        },
    )

    flux = await whats_new.whats_new()

    assert flux["version"] == "0.2.0"
    assert [e["text"] for e in flux["sections"]["Fixed"]] == ["recent"]


@pytest.mark.asyncio
async def test_la_tranche_est_bornee_et_dit_ce_qu_elle_omet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Envoyer cent trente kilo-octets pour en afficher six serait payer une 3G pour rien."""
    lignes = [{"text": f"entree {i}"} for i in range(20)]
    _pose(
        tmp_path,
        monkeypatch,
        {
            "product": "klassci-college-backend",
            "versions": [{"version": "Unreleased", "sections": {"Added": lignes}}],
        },
    )

    flux = await whats_new.whats_new()

    assert len(flux["sections"]["Added"]) == whats_new.PAR_SECTION
    # L'ecran doit pouvoir dire « et 14 autres » plutot que laisser croire
    # qu'il montre tout.
    assert flux["total"] == 20


@pytest.mark.asyncio
async def test_une_section_vide_ne_sort_pas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un titre sans ligne dessous est un rendez-vous manque."""
    _pose(
        tmp_path,
        monkeypatch,
        {
            "product": "x",
            "versions": [
                {"version": "Unreleased", "sections": {"Added": [], "Fixed": [{"text": "a"}]}}
            ],
        },
    )

    assert list((await whats_new.whats_new())["sections"]) == ["Fixed"]
