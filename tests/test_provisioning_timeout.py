"""Un dépassement pendant le provisionnement d'une école doit dire quoi faire.

Créer une école joue soixante-quinze révisions d'affilée. Si le délai est
dépassé, alembic n'est pas mis en pause : il est **tué en pleine migration**. La
base existe déjà — elle a été créée à l'étape précédente — et se retrouve à
moitié migrée.

Ce qui remontait alors était une `TimeoutExpired` nue : elle ne disait ni où on
en était, ni que la base existait, ni qu'on pouvait relancer. Quelqu'un devant
une école à moitié créée mérite mieux qu'un nom d'exception.
"""

import subprocess

import pytest

from app.core.config import settings
from app.services.tenants import provisioning


@pytest.mark.asyncio
async def test_un_depassement_dit_ce_qui_reste_en_base(monkeypatch) -> None:
    """Le message doit nommer l'école, l'état de la base, et la reprise."""

    def _toujours_trop_long(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="alembic", timeout=1)

    monkeypatch.setattr(subprocess, "run", _toujours_trop_long)

    with pytest.raises(RuntimeError) as erreur:
        await provisioning.run_migrations("lycee-neuf")

    message = str(erreur.value)
    assert "lycee-neuf" in message, "le message doit nommer l'école concernée"
    assert "partiellement migree" in message, (
        "il doit dire que la base existe et n'est pas finie — c'est ce qui décide de la suite"
    )
    assert "Relancer" in message, "il doit donner la reprise, pas seulement le constat"


@pytest.mark.asyncio
async def test_le_depassement_ne_remonte_pas_nu(monkeypatch) -> None:
    """`TimeoutExpired` seule ne dit rien à qui la reçoit.

    La distinction compte : le code appelant attrape `RuntimeError` comme un
    échec de provisionnement traité, pendant qu'une `TimeoutExpired` traverse
    en exception inattendue.
    """

    def _toujours_trop_long(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="alembic", timeout=1)

    monkeypatch.setattr(subprocess, "run", _toujours_trop_long)

    with pytest.raises(RuntimeError):
        await provisioning.run_migrations("lycee-neuf")

    # Et la cause d'origine reste attachée, pour le journal.
    with pytest.raises(RuntimeError) as erreur:
        await provisioning.run_migrations("lycee-neuf")
    assert isinstance(erreur.value.__cause__, subprocess.TimeoutExpired)


def test_le_delai_est_le_meme_des_deux_cotes() -> None:
    """Le provisionnement et la migration de masse partagent un seul réglage.

    Ce sont la même opération, avec le même mode de panne. Deux valeurs qui
    dérivent finiraient par en contredire une : celui qui relève le délai après
    un incident ne pense pas à chercher le second endroit.
    """
    from app.cli import migrate_all

    assert migrate_all._delai() == settings.ALEMBIC_TIMEOUT_SECONDS
    assert settings.ALEMBIC_TIMEOUT_SECONDS >= 600, (
        "soixante-quinze révisions sur une base neuve demandent de la marge ; "
        "un délai trop court fabrique précisément la panne qu'on veut éviter"
    )
