"""Le balayage du sas, et la panne qu'il ne doit surtout pas taire.

Le TTL Redis efface la session, pas le fichier. Quatre chemins effacent un
dépôt — confirmer, reprendre, révoquer, fermer l'écran — et tous supposent
quelqu'un devant un écran. Le cinquième cas n'a personne, et sans balayage le
sas accumulerait des photos d'élèves indéfiniment sur un volume persistant.

Le test qui compte le plus est le dernier : la tâche tourne dans le conteneur
`worker`, qui n'est pas celui qui écrit. Si le volume du sas n'y est pas monté,
le balayeur regarde un dossier vide pendant que les images s'entassent
ailleurs — et un rapport à zéro se lit comme « rien à faire ». Il doit donc
distinguer « rien à effacer » de « je ne regarde pas au bon endroit ».
"""

import logging
import os
import time
from pathlib import Path

import pytest

from app.core.celery_app import celery_app
from app.services.upload_handoff_service import SESSION_TTL_SECONDS
from app.tasks.handoff_tasks import (
    AGE_MAXIMAL_SECONDS,
    sweep_staged_handoffs,
)
from app.utils import handoff_storage

JPEG = b"\xff\xd8\xff" + b"0" * 64


@pytest.fixture
def sas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    racine = tmp_path / "handoff"
    racine.mkdir()
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", racine)
    return racine


def _depot(sas: Path, nom: str, *, age_secondes: float) -> Path:
    chemin = sas / nom
    chemin.write_bytes(JPEG)
    quand = time.time() - age_secondes
    os.utime(chemin, (quand, quand))
    return chemin


# ---------------------------------------------------------------------------
# Ce que le balayage efface, et ce qu'il n'efface pas
# ---------------------------------------------------------------------------


def test_un_depot_qu_aucune_session_ne_peut_plus_revendiquer_est_efface(sas: Path) -> None:
    """Sans lui, chaque envoi non confirmé reste sur le volume pour toujours."""
    orphelin = _depot(sas, "vieille_abcd1234.jpg", age_secondes=AGE_MAXIMAL_SECONDS + 60)

    rapport = sweep_staged_handoffs()

    assert not orphelin.exists()
    assert rapport["effaces"] == 1
    assert rapport["octets_liberes"] == len(JPEG)
    assert rapport["racine_absente"] is False


def test_un_depot_qu_un_operateur_regarde_peut_etre_n_est_pas_efface(sas: Path) -> None:
    """L'erreur coûteuse est d'effacer la photo qu'on est en train de valider.

    Garder une image dix minutes de trop ne coûte rien ; la faire disparaître
    sous les yeux de l'opérateur lui fait rappeler l'élève.
    """
    frais = _depot(sas, "fraiche_abcd1234.jpg", age_secondes=30)

    rapport = sweep_staged_handoffs()

    assert frais.exists()
    assert rapport["vus"] == 1
    assert rapport["effaces"] == 0


def test_le_seuil_couvre_la_duree_d_une_session_avec_de_la_marge(sas: Path) -> None:
    """Un dépôt est écrit APRÈS l'ouverture de sa session : il est plus jeune qu'elle.

    Le seuil doit donc dépasser la durée de vie d'une session, sans quoi le
    balayage passerait sous une session encore vivante.
    """
    assert AGE_MAXIMAL_SECONDS > SESSION_TTL_SECONDS

    limite = _depot(sas, "limite_abcd1234.jpg", age_secondes=SESSION_TTL_SECONDS + 5)
    sweep_staged_handoffs()

    assert limite.exists()


def test_un_dossier_du_sas_n_est_pas_compte_comme_un_depot(sas: Path) -> None:
    """Le sas est plat. Un dossier qui s'y trouve n'est pas de nous : on n'y touche pas."""
    (sas / "sous-dossier").mkdir()

    rapport = sweep_staged_handoffs()

    assert rapport["vus"] == 0
    assert (sas / "sous-dossier").exists()


def test_un_fichier_qui_resiste_n_arrete_pas_le_balayage(
    sas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un échec est compté et remonté ; les autres dépôts sont quand même traités.

    Un compteur d'échecs qui reste à zéro alors que rien n'a été effacé serait
    le pire des deux mondes : un rapport rassurant sur un sas qui ne se vide pas.
    """
    _depot(sas, "coince_abcd1234.jpg", age_secondes=AGE_MAXIMAL_SECONDS + 60)
    vrai_unlink = Path.unlink

    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        if self.name.startswith("coince"):
            raise OSError(13, "Permission denied")
        vrai_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    _depot(sas, "libre_abcd1234.jpg", age_secondes=AGE_MAXIMAL_SECONDS + 60)

    rapport = sweep_staged_handoffs()

    assert rapport["echecs"] == 1
    assert rapport["effaces"] == 1


# ---------------------------------------------------------------------------
# La panne qui se tait : un sas que ce conteneur ne voit pas
# ---------------------------------------------------------------------------


def test_une_racine_absente_est_signalee_et_non_creee(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """La tâche tourne dans `worker`, le sas est écrit par `backend`.

    Sans le volume partagé, le balayeur regarderait un dossier vide et
    rapporterait zéro, chaque quart d'heure, pendant que les photos s'entassent
    dans la couche jetable de l'autre conteneur. Le créer « au cas où » rendrait
    cette panne indiscernable d'un sas vide : on la dit, et on s'arrête.
    """
    absente = tmp_path / "jamais-montee"
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", absente)

    with caplog.at_level(logging.ERROR):
        rapport = sweep_staged_handoffs()

    assert rapport["racine_absente"] is True
    assert rapport["effaces"] == 0
    assert not absente.exists(), "un dossier créé ici masquerait un volume mal monté"
    assert "volume" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Le porteur : la tâche est bien celle que l'ordonnanceur déclenche
# ---------------------------------------------------------------------------


def test_la_tache_est_enregistree_et_planifiee() -> None:
    """Une tâche non incluse ne s'exécute pas, et beat la déclencherait dans le vide."""
    assert "app.tasks.handoff_tasks" in celery_app.conf.include
    planifiees = {
        entree["task"]
        for entree in celery_app.conf.beat_schedule.values()  # type: ignore[union-attr]
    }
    assert "handoff.sweep_staged" in planifiees
