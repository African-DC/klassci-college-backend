"""Un dépassement de délai pendant une migration doit être un échec, fort.

`migrate_all` coupe alembic au bout d'un délai. Le dépassement ne suspend rien :
il TUE la migration en cours et laisse la base dans l'état partiel dont on ne
sort qu'à la main — le pire des quatre cas listés en tête de la révision 0075.

Le taire serait le pire des deux mondes : l'outil sortirait à zéro en annonçant
« All N tenants migrated successfully » sur une base à moitié migrée, et
l'opérateur enchaînerait sur le déploiement du code neuf. C'est exactement ce
que garde ce fichier, parce que rien d'autre ne le gardait.
"""

import subprocess

import pytest

from app.cli import migrate_all


@pytest.mark.asyncio
async def test_un_depassement_de_delai_fait_echouer_le_deploiement(monkeypatch) -> None:
    """Une base qui dépasse le délai doit sortir en échec, en le nommant."""
    monkeypatch.setattr(migrate_all, "list_tenant_databases", _bases(["local", "rostan-bouake"]))

    def _toujours_trop_long(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="alembic", timeout=1)

    monkeypatch.setattr(subprocess, "run", _toujours_trop_long)

    with pytest.raises(SystemExit) as sortie:
        await migrate_all.migrate_all("head")

    assert sortie.value.code == 1, (
        "sortir à zéro laisserait l'opérateur déployer le code neuf sur une base à moitié migrée"
    )


@pytest.mark.asyncio
async def test_une_base_qui_deborde_n_empeche_pas_les_autres(monkeypatch) -> None:
    """La première base peut déborder sans que les suivantes soient abandonnées.

    Une exception nue aurait remonté au premier dépassement : la seconde école
    serait restée non migrée sans qu'on sache seulement qu'elle existait.
    """
    monkeypatch.setattr(migrate_all, "list_tenant_databases", _bases(["local", "rostan-bouake"]))
    tentees: list[str] = []

    def _premiere_trop_longue(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        tenant = kwargs["env"]["TENANT_ID"]
        tentees.append(tenant)
        if tenant == "local":
            raise subprocess.TimeoutExpired(cmd="alembic", timeout=1)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _premiere_trop_longue)

    with pytest.raises(SystemExit):
        await migrate_all.migrate_all("head")

    assert tentees == ["local", "rostan-bouake"], "chaque base doit être tentée"


def _bases(noms: list[str]):
    """Remplace l'énumération des bases, qui a besoin d'un vrai moteur."""

    async def _lister() -> list[str]:
        return noms

    return _lister
