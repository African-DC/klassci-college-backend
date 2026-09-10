"""Balayage du sas : les dépôts qu'aucun opérateur n'a confirmés.

Ce que le TTL Redis ne fait pas
==============================

Une session de dépôt expire toute seule : Redis efface ses deux clés au bout de
dix minutes, sans que personne n'ait à passer. Le FICHIER, lui, reste. Quatre
chemins l'effacent — confirmer, reprendre, révoquer, fermer l'écran — et ils
supposent tous quelqu'un devant un écran. Le cinquième cas n'a personne : le
téléphone a envoyé la photo, l'opérateur a été appelé ailleurs, l'écran s'est
fermé sans révocation, ou le navigateur a été tué. Ce fichier-là n'a plus de
session, plus d'URL, et plus rien qui le désigne.

Sans ce balayage, le sas accumulerait des photos d'élèves indéfiniment sur un
volume persistant. Et la fonctionnalité fabriquerait une fuite de disque
exactement proportionnelle à son succès : chaque « Reprendre » est une image de
plus.

Où cette tâche tourne, et pourquoi c'est LA question
====================================================

Elle tourne dans le conteneur `worker`, qui n'est pas celui qui écrit. Le
backend reçoit les dépôts ; le worker exécute les tâches. Deux conteneurs, deux
systèmes de fichiers — sauf si le MÊME volume est monté aux deux, sur le même
chemin, avec la même variable de racine.

C'est fait, et c'est délibéré : `deploy/linux/docker-compose.dokploy.yml` monte
`klassci_handoff:/app/handoff` et déclare `HANDOFF_ROOT: /app/handoff` sur
`backend` ET sur `worker`. Le fichier compose porte lui-même la leçon, apprise
sur les téléversements : « ce compose seul monterait le volume là où le code
n'écrit pas encore, et le code seul écrirait là où aucun volume n'est monté ».

`beat` n'a ni volume ni racine, et n'en veut pas : il publie l'heure du
déclencheur dans Redis, il n'exécute aucune tâche et n'ouvre jamais un fichier.

Le balayage ne crée PAS la racine
=================================

C'est le point qui rend l'erreur visible plutôt que silencieuse. Si le dossier
n'existe pas, cette tâche le dit et s'arrête ; elle ne le crée pas. Un
`makedirs` « au cas où » fabriquerait un dossier vide dans la couche jetable du
worker, et le balayage rapporterait sereinement zéro fichier effacé, chaque
quart d'heure, pendant que les photos s'entassent dans l'autre conteneur. Un
rapport à zéro se lit comme « rien à faire » ; c'est exactement la panne qu'on
ne voit pas. Ici, un volume mal monté sort en `ERROR` dans les journaux et en
`racine_absente` dans le résultat de la tâche.

Pas de boucle sur les établissements
====================================

À la différence du balayage des journées de caisse, celui-ci ne connaît pas les
écoles : le sas est un dossier de fichiers, pas une base. Un nom de dépôt porte
l'identifiant de sa session, jamais un tenant — le cloisonnement par
établissement est dans la clé Redis, et il n'a rien à faire ici.
"""

import logging
import time
from pathlib import Path
from typing import Any

from app.core.celery_app import celery_app
from app.services.upload_handoff_service import SESSION_TTL_SECONDS
from app.utils import handoff_storage

logger = logging.getLogger(__name__)

#: Au-delà de quel âge un fichier du sas n'appartient plus à personne.
#:
#: Un dépôt est écrit APRÈS l'ouverture de sa session, donc il est toujours plus
#: jeune qu'elle : passé la durée de vie d'une session, plus aucune session
#: vivante ne peut le revendiquer. Le double sert de marge — une horloge qui
#: dérive entre deux conteneurs, une tâche qui démarre en retard — parce que
#: l'erreur coûteuse est d'effacer la photo qu'un opérateur est en train de
#: regarder, pas d'en garder une dix minutes de trop.
AGE_MAXIMAL_SECONDS = SESSION_TTL_SECONDS * 2


def sweep_staged_handoffs(max_age_seconds: int | None = None) -> dict[str, Any]:
    """Efface du sas les dépôts trop vieux pour appartenir encore à une session.

    Rendu séparément de la tâche Celery pour être appelable — et testable —
    sans courtier ni ordonnanceur.

    Un fichier qui résiste n'arrête pas le balayage : il est compté et le
    passage continue. Le compte des échecs remonte dans le résultat, pour qu'un
    silence ne passe pas pour un succès.
    """
    limite = max_age_seconds if max_age_seconds is not None else AGE_MAXIMAL_SECONDS
    racine: Path = handoff_storage.HANDOFF_ROOT
    rapport: dict[str, Any] = {
        "racine": str(racine),
        "racine_absente": False,
        "vus": 0,
        "effaces": 0,
        "octets_liberes": 0,
        "echecs": 0,
    }

    if not racine.is_dir():
        # Voir l'en-tête : on ne la crée pas, on la signale. Un dossier créé ici
        # rendrait un volume mal monté indiscernable d'un sas vide.
        rapport["racine_absente"] = True
        logger.error(
            "Balayage du sas impossible : %s n'existe pas. "
            "Le volume du sas n'est probablement pas monté sur ce conteneur "
            "(HANDOFF_ROOT et klassci_handoff, cf. docker-compose).",
            racine,
        )
        return rapport

    maintenant = time.time()
    for chemin in racine.iterdir():
        if not chemin.is_file():
            continue
        rapport["vus"] += 1
        try:
            infos = chemin.stat()
            if maintenant - infos.st_mtime <= limite:
                continue
            chemin.unlink()
        except OSError:
            rapport["echecs"] += 1
            logger.warning("Dépôt orphelin non supprimé : %s", chemin, exc_info=True)
            continue
        rapport["effaces"] += 1
        rapport["octets_liberes"] += infos.st_size

    if rapport["effaces"]:
        logger.info("Balayage du sas : %s", rapport)
    return rapport


@celery_app.task(bind=True, name="handoff.sweep_staged")  # type: ignore[misc]
def sweep_staged_handoffs_task(self: Any, max_age_seconds: int | None = None) -> dict[str, Any]:
    """Déclenchée par l'ordonnanceur. Appelable seule pour un balayage immédiat."""
    return sweep_staged_handoffs(max_age_seconds)
